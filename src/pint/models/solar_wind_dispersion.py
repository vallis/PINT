"""Dispersion due to the solar wind."""
from termios import B300
from warnings import warn

import astropy.constants as const
import astropy.units as u
import astropy.time
import numpy as np
import scipy.special

from pint.models.dispersion_model import Dispersion, DMconst
from pint.models.parameter import floatParameter, prefixParameter
import pint.utils
from pint.models.timing_model import DelayComponent, MissingParameter, MissingTOAs
from pint.toa_select import TOASelect


def _dm_p_int(b, z, p):
    """Integral function for DM calculation
    from https://github.com/nanograv/enterprise_extensions/blob/master/enterprise_extensions/chromatic/solar_wind.py#L299

    See Figure 1 of Hazboun et al. (2022) for definitions of b, z

    Parameters
    ----------
    b : astropy.quantity.Quantity
        Impact parameter
    z : astropy.quantity.Quantity
        distance from Earth to closest point to the Sun
    p : float
        power-law index

    Returns
    -------
    astropy.quantity.Quantity
    """
    return (z / b) * scipy.special.hyp2f1(
        0.5, p / 2.0, 1.5, -((z**2) / b**2).decompose().value
    )


def _gamma_function(p):
    """The second term in Eqn. 12 of Hazboun et al. involving Gamma functions
    Note that this needs to be multiplied by b*sqrt(pi)/2

    Parameters
    ----------
    p : float
        power-law index

    Returns
    -------
    float
    """
    return scipy.special.gamma(p / 2 - 0.5) / scipy.special.gamma(p / 2)


def _d_gamma_function_dp(p):
    """Derivative of the second term in Eqn. 12 of Hazboun et al. involving Gamma functions wrt p
    Note that this needs to be multiplied by b*sqrt(pi)/2

    Parameters
    ----------
    p : float
        power-law index

    Returns
    -------
    float
    """
    return scipy.special.gamma(p / 2 - 0.5) * scipy.special.polygamma(
        0, p / 2 - 0.5
    ) / 2 / scipy.special.gamma(p / 2) - scipy.special.gamma(
        p / 2 - 0.5
    ) * scipy.special.polygamma(
        0, p / 2
    ) / 2 / scipy.special.gamma(
        p / 2
    )


def _hypergeom_function(b, z, p):
    """The first term in Eqn. 12 of Hazboun et al. involving hypergeometric functions
    Note that this needs to be multiplied by b

    Parameters
    ----------
    b : astropy.quantity.Quantity
        Impact parameter
    z : astropy.quantity.Quantity
        distance from Earth to closest point to the Sun
    p : float
        power-law index

    Returns
    -------
    astropy.quantity.Quantity
    """
    theta = np.arctan2(b, z)
    return (1 / np.tan(theta)) * scipy.special.hyp2f1(
        0.5, p / 2.0, 1.5, -((1 / np.tan(theta)).value ** 2)
    )


def _d_hypergeom_function_dp(b, z, p):
    """Derivative of the first term in Eqn. 12 of Hazboun et al. involving hypergeometric functions wrt p
    Note that this needs to be multiplied by b

    Parameters
    ----------
    b : astropy.quantity.Quantity
        Impact parameter
    z : astropy.quantity.Quantity
        distance from Earth to closest point to the Sun
    p : float
        power-law index

    Returns
    -------
    astropy.quantity.Quantity
    """
    theta = np.arctan2(b, z)
    x = theta.to_value(u.rad) - np.pi / 2
    # the result of a order 4,4 Pade expansion of
    # cot(theta) * hypergeom([1/2, p/2],[3/2],-cot(theta)**2)
    # near theta=Pi/2
    # in Maple:
    # with(numapprox):
    # with(CodeGeneration):
    # Python(simplify(subs(theta = x + Pi/2, diff(pade(cot(theta)*hypergeom([1/2, p/2], [3/2], -cot(theta)^2), theta = Pi/2, [4, 4]), p))));
    return (
        8580
        * x**3
        * (
            (
                p**4
                - 0.76e2 / 0.11e2 * p**3
                + 0.2996e4 / 0.429e3 * p**2
                + 0.5248e4 / 0.429e3 * p
                - 0.1984e4 / 0.429e3
            )
            * x**4
            + 0.84e2
            / 0.11e2
            * (p**2 - 0.115e3 / 0.39e2 * p - 0.44e2 / 0.39e2)
            * (p + 4)
            * x**2
            + 0.1960e4 / 0.143e3 * (p + 4) ** 2
        )
        / (
            39 * x**4 * p**3
            - 186 * x**4 * p**2
            + 200 * x**4 * p
            + 360 * x**2 * p**2
            + 32 * x**4
            - 480 * x**2 * p
            - 1440 * x**2
            + 840 * p
            + 3360
        )
        ** 2
    )


class SolarWindDispersion(Dispersion):
    """Dispersion due to the solar wind (basic model).

    The model is a simple spherically-symmetric model that is fit
    in its constant amplitude.

    For ``SWM==0`` it assumes a power-law index of 2 (Edwards et al.)

    For ``SWM==1`` it can have any power-law index (You et al., Hazboun et al.), which can also be fit

    Parameters supported:

    .. paramtable::
        :class: pint.models.solar_wind_dispersion.SolarWindDispersion

    References
    ----------
    - Edwards et al. 2006, MNRAS, 372, 1549; Setion 2.5.4
    - Madison et al. 2019, ApJ, 872, 150; Section 3.1.
    - Hazboun et al. (2022, ApJ, 929, 39)
    - You et al. (2012, MNRAS, 422, 1160)
    """

    register = True
    category = "solar_wind"

    def __init__(self):
        super().__init__()
        self.add_param(
            floatParameter(
                name="NE_SW",
                units="cm^-3",
                value=0.0,
                aliases=["NE1AU", "SOLARN0"],
                description="Solar Wind density at 1 AU",
            )
        )
        self.add_param(
            floatParameter(
                name="SWP",
                value=2.0,
                units="",
                description="Solar Wind Model radial power-law index (only for SWM=1)",
            )
        )
        self.add_param(
            floatParameter(
                name="SWM",
                value=0.0,
                units="",
                description="Solar Wind Model (0 is from Edwards+ 2006, 1 is from You+2007,2012/Hazboun+ 2022)",
            )
        )
        self.dm_value_funcs += [self.solar_wind_dm]
        self.delay_funcs_component += [self.solar_wind_delay]
        self.set_special_params(["NE_SW", "SWM", "SWP"])

    def setup(self):
        super().setup()
        self.register_dm_deriv_funcs(self.d_dm_d_ne_sw, "NE_SW")
        self.register_deriv_funcs(self.d_delay_d_ne_sw, "NE_SW")
        self.register_dm_deriv_funcs(self.d_dm_d_swp, "SWP")
        self.register_deriv_funcs(self.d_delay_d_swp, "SWP")

    def solar_wind_geometry(self, toas):
        """Return the geometry of solar wind dispersion.

        For SWM==0:
            Implements the geometry part of equations 29, 30 of Edwards et al. 2006,
            (i.e., without the n0, the solar wind DM amplitude part.)
            Their rho is given as theta here.

            rvec: radial vector from observatory to the center of the Sun
            pos: pulsar position
        For SWM==1:
            Implements Eqn. 11 of Hazboun et al. (2022)

        Parameters
        ----------
        toas : pint.toa.TOAs

        Returns
        -------
        astropy.quantity.Quantity
        """
        swm = self.SWM.value
        p = self.SWP.value

        if swm == 0:
            angle, r = self._parent.sun_angle(toas, also_distance=True)
            rho = np.pi - angle.to_value(u.rad)
            solar_wind_geometry = const.au**2.0 * rho / (r * np.sin(rho))
            return solar_wind_geometry.to(u.pc)
        elif swm == 1:
            # get elongation angle, distance from Earth to Sun
            theta, r = self._parent.sun_angle(toas, also_distance=True)
            # impact parameter
            b = r * np.sin(theta)
            # distance from the Earth to the impact point
            z_sun = r * np.cos(theta)
            # a big value for comparison
            # this is what Enterprise uses
            z_p = (1e14 * u.s * const.c).to(b.unit)
            if p > 1:
                solar_wind_geometry = (
                    (1 / b.to_value(u.AU)) ** p
                    * b
                    * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
                )
            else:
                raise NotImplementedError(
                    "Solar Dispersion Delay not implemented for power-law index p <= 1"
                )
            return solar_wind_geometry.to(u.pc)
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for SWM %d" % swm
            )

    def solar_wind_dm(self, toas):
        """Return the solar wind dispersion measure.

        SWM==0:
            Uses equations 29, 30 of Edwards et al. 2006.
        SWM==1:
            Hazboun et al. 2022
        """
        if self.NE_SW.value == 0:
            return np.zeros(len(toas)) * u.pc / u.cm**3
        if self.SWM.value == 0 or self.SWM.value == 1:
            solar_wind_geometry = self.solar_wind_geometry(toas)
            solar_wind_dm = self.NE_SW.quantity * solar_wind_geometry
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for SWM %d" % self.SWM.value
            )
        return solar_wind_dm.to(u.pc / u.cm**3)

    def solar_wind_delay(self, toas, acc_delay=None):
        """This is a wrapper function to compute solar wind dispersion delay."""
        if self.NE_SW.value == 0:
            return np.zeros(len(toas)) * u.s
        return self.dispersion_type_delay(toas)

    def d_dm_d_ne_sw(self, toas, param_name, acc_delay=None):
        """Derivative of of DM wrt the solar wind ne amplitude."""
        if self.SWM.value == 0 or self.SWM.value == 1:
            solar_wind_geometry = self.solar_wind_geometry(toas)
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for SWM %d" % self.SWM.value
            )
        return solar_wind_geometry

    def d_delay_d_ne_sw(self, toas, param_name, acc_delay=None):
        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = toas.table["freq"]
        deriv = self.d_delay_d_dmparam(toas, "NE_SW")
        deriv[bfreq < 1.0 * u.MHz] = 0.0
        return deriv

    def d_solar_wind_geometry_d_swp(self, toas, param_name, acc_delay=None):
        """Derivative of solar_wind_geometry (path length) wrt power-law index p

        The evaluation is done using Eqn. 12 in Hazboun et al. (2022).  The first term
        involving hypergeometric functions (:func:`_hypergeom_function`)
        has the derivative computed approximately using a Pade expansion (:func:`_d_hypergeom_function_dp`).
        The second uses gamma functions (:func:`_gamma_function`) and has the derivative computed
        using polygamma functions (:func:`_d_gamma_function_dp`).

        """
        if self.SWM.value == 0:
            raise ValueError(
                "Solar Wind power-law index not valid for SWM %d" % self.SWM.value
            )
        elif self.SWM.value == 1:
            # get elongation angle, distance from Earth to Sun
            theta, r = self._parent.sun_angle(toas, also_distance=True)
            # impact parameter
            b = r * np.sin(theta)
            # distance from the Earth to the impact point
            z_sun = r * np.cos(theta)
            # a big value for comparison
            # this is what Enterprise uses
            z_p = (1e14 * u.s * const.c).to(b.unit)
            p = self.SWP.value
            if p > 1:
                return (1 / b.to_value(u.AU)) ** p * (
                    b * _d_hypergeom_function_dp(b, z_sun, p)
                    + (b * np.sqrt(np.pi) / 2) * _d_gamma_function_dp(p)
                ) - (1 / b.to_value(u.AU)) ** p * np.log(b.to_value(u.AU)) * (
                    b * _hypergeom_function(b, z_sun, p)
                    + (b * np.sqrt(np.pi) / 2) * _gamma_function(p)
                )
            else:
                return np.inf * np.ones(len(toas)) * u.pc
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for SWM %d" % self.SWM.value
            )

    def d_dm_d_swp(self, toas, param_name, acc_delay=None):
        d_geometry_dp = self.d_solar_wind_geometry_d_swp(
            toas, param_name, acc_delay=acc_delay
        )
        return self.NE_SW.quantity * d_geometry_dp

    def d_delay_d_swp(self, toas, param_name, acc_delay=None):
        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = toas.table["freq"]
        deriv = self.d_delay_d_dmparam(toas, "SWP")
        deriv[bfreq < 1.0 * u.MHz] = 0.0
        return deriv

    def print_par(self, format="pint"):
        result = ""
        result += getattr(self, "NE_SW").as_parfile_line(format=format)
        result += getattr(self, "SWM").as_parfile_line(format=format)
        if self.SWM.value == 1:
            result += getattr(self, "SWP").as_parfile_line(format=format)
        return result

    def get_max_dm(self):
        """Return approximate maximum DM from the Solar Wind (at conjunction)

        Simplified model that assumes a circular orbit

        Returns
        -------
        astropy.quantity.Quantity
        """
        coord = self._parent.get_psr_coords()
        if self._parent.POSEPOCH.value is not None:
            t0 = self._parent.POSEPOCH.quantity
        elif self._parent.PEPOCH.value is not None:
            t0 = self._parent.PEPOCH.quantity
        else:
            t0 = astropy.time.Time(50000, format="mjd")
        # time and distance of conjunction
        t0, elongation = pint.utils.get_conjunction(coord, t0, precision="high")
        if self.SWM.value == 0:
            r = 1 * u.AU
            rho = (180 * u.deg - elongation).to(u.rad)
            return (
                self.NE_SW.quantity * (const.au**2.0 * rho / (r * np.sin(rho)))
            ).to(u.pc / u.cm**3, equivalencies=u.dimensionless_angles())
        elif self.SWM.value == 1:
            p = self.SWP.value
            theta = elongation
            r = 1 * u.AU
            # impact parameter
            b = r * np.sin(theta)
            # distance from the Earth to the impact point
            z_sun = r * np.cos(theta)
            # a big value for comparison
            # this is what Enterprise uses
            z_p = (1e14 * u.s * const.c).to(b.unit)
            if p > 1:
                solar_wind_geometry = (
                    (1 / b.to_value(u.AU)) ** p
                    * b
                    * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
                )
            else:
                raise NotImplementedError(
                    "Solar Dispersion Delay not implemented for power-law index p <= 1"
                )
            return (solar_wind_geometry * self.NE_SW.quantity).to(u.pc / u.cm**3)
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for SWM %d" % self.SWM.value
            )

    def get_min_dm(self):
        """Return approximate minimum DM from the Solar Wind (180deg away from conjunction)

        Simplified model that assumes a circular orbit

        Returns
        -------
        astropy.quantity.Quantity
        """
        coord = self._parent.get_psr_coords()
        if self._parent.POSEPOCH.value is not None:
            t0 = self._parent.POSEPOCH.quantity
        elif self._parent.PEPOCH.value is not None:
            t0 = self._parent.PEPOCH.quantity
        else:
            t0 = astropy.time.Time(50000, format="mjd")
        # time and distance of conjunction
        t0, elongation = pint.utils.get_conjunction(coord, t0, precision="high")
        if self.SWM.value == 0:
            r = 1 * u.AU
            rho = (elongation).to(u.rad)
            return (
                self.NE_SW.quantity * (const.au**2.0 * rho / (r * np.sin(rho)))
            ).to(u.pc / u.cm**3, equivalencies=u.dimensionless_angles())
        elif self.SWM.value == 1:
            p = self.SWP.value
            # for the min
            theta = 180 * u.deg - elongation
            r = 1 * u.AU
            # impact parameter
            b = r * np.sin(theta)
            # distance from the Earth to the impact point
            z_sun = r * np.cos(theta)
            # a big value for comparison
            # this is what Enterprise uses
            z_p = (1e14 * u.s * const.c).to(b.unit)
            if p > 1:
                solar_wind_geometry = (
                    (1 / b.to_value(u.AU)) ** p
                    * b
                    * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
                )
            else:
                raise NotImplementedError(
                    "Solar Dispersion Delay not implemented for power-law index p <= 1"
                )
            return (solar_wind_geometry * self.NE_SW.quantity).to(u.pc / u.cm**3)
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for SWM %d" % self.SWM.value
            )


class SolarWindDispersionX(Dispersion):
    """This class provides a SWX model - multiple Solar Wind segments.

    This model lets the user specify time ranges and fit for a different
    SWX (solar wind density at 1 AU) value and SWXP (radial power-law index) in each time range.

    The default radial power-law index value of 2 corresponds to the Edwards et al. model.
    Other values are for the You et al./Hazboun et al. model.

    Parameters supported:

    .. paramtable::
        :class: pint.models.solar_wind_dispersion.SolarWindDispersionX

    References
    ----------
    - Edwards et al. 2006, MNRAS, 372, 1549; Setion 2.5.4
    - Madison et al. 2019, ApJ, 872, 150; Section 3.1.
    - Hazboun et al. (2022, ApJ, 929, 39)
    - You et al. (2012, MNRAS, 422, 1160)
    """

    register = True
    category = "solar_windx"

    def __init__(self):
        super().__init__()

        self.add_swx_range(None, None, swx=0, swxp=2, frozen=False, index=1)

        self.set_special_params(["SWX_0001", "SWXP_0001", "SWXR1_0001", "SWXR2_0001"])
        self.dm_value_funcs += [self.swx_dm]
        self.delay_funcs_component += [self.swx_delay]

    def solar_wind_geometry(self, toas, p=2):
        """Return the geometry of solar wind dispersion.

        Implements Eqn. 11 of Hazboun et al. (2022)

        Parameters
        ----------
        toas : pint.toa.TOAs
        p : float, optional
            Radial power-law index

        Returns
        -------
        astropy.quantity.Quantity
        """

        # get elongation angle, distance from Earth to Sun
        theta, r = self._parent.sun_angle(toas, also_distance=True)
        # impact parameter
        b = r * np.sin(theta)
        # distance from the Earth to the impact point
        z_sun = r * np.cos(theta)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b.unit)
        if p > 1:
            solar_wind_geometry = (
                (1 / b.to_value(u.AU)) ** p
                * b
                * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
            )
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for power-law index p <= 1"
            )
        return solar_wind_geometry.to(u.pc)

    def d_solar_wind_geometry_d_swxp(self, toas, p):
        """Derivative of solar_wind_geometry (path length) wrt power-law index p

        The evaluation is done using Eqn. 12 in Hazboun et al. (2022).  The first term
        involving hypergeometric functions (:func:`_hypergeom_function`)
        has the derivative computed approximately using a Pade expansion (:func:`_d_hypergeom_function_dp`).
        The second uses gamma functions (:func:`_gamma_function`) and has the derivative computed
        using polygamma functions (:func:`_d_gamma_function_dp`).

        Parameters
        ----------
        toas : pint.toa.TOAs
        p : float, optional
            Radial power-law index

        Returns
        -------
        astropy.quantity.Quantity
        """
        # get elongation angle, distance from Earth to Sun
        theta, r = self._parent.sun_angle(toas, also_distance=True)
        # impact parameter
        b = r * np.sin(theta)
        # distance from the Earth to the impact point
        z_sun = r * np.cos(theta)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b.unit)
        if p > 1:
            return (1 / b.to_value(u.AU)) ** p * (
                b * _d_hypergeom_function_dp(b, z_sun, p)
                + (b * np.sqrt(np.pi) / 2) * _d_gamma_function_dp(p)
            ) - (1 / b.to_value(u.AU)) ** p * np.log(b.to_value(u.AU)) * (
                b * _hypergeom_function(b, z_sun, p)
                + (b * np.sqrt(np.pi) / 2) * _gamma_function(p)
            )
        else:
            return np.inf * np.ones(len(toas)) * u.pc

    def add_swx_range(self, mjd_start, mjd_end, index=None, swx=0, swxp=2, frozen=True):
        """Add SWX range to a dispersion model with specified start/end MJD, SWX, and power-law index

        Parameters
        ----------

        mjd_start : float
            MJD for beginning of DMX event.
        mjd_end : float
            MJD for end of DMX event.
        index : int, None
            Integer label for DMX event. If None, will increment largest used index by 1.
        swx : float
            Solar wind density at 1 AU
        swxp : float
            Solar wind power-law index
        frozen : bool
            Indicates whether SWX and SWXP will be fit.

        Returns
        -------

        index : int
            Index that has been assigned to new SWX event.

        """

        #### Setting up the SWX title convention. If index is None, want to increment the current max SWX index by 1.
        if index is None:
            dct = self.get_prefix_mapping_component("SWX_")
            index = np.max(list(dct.keys())) + 1
        i = f"{int(index):04d}"

        if mjd_end is not None and mjd_start is not None:
            if mjd_end < mjd_start:
                raise ValueError("Starting MJD is greater than ending MJD.")
        elif mjd_start != mjd_end:
            raise ValueError("Only one MJD bound is set.")

        if int(index) in self.get_prefix_mapping_component("SWX_"):
            raise ValueError(
                "Index '%s' is already in use in this model. Please choose another."
                % index
            )

        self.add_param(
            prefixParameter(
                name="SWX_" + i,
                units="cm^-3",
                value=swx,
                description="Solar Wind density at 1 AU",
                parameter_type="float",
                frozen=frozen,
            )
        )
        self.add_param(
            prefixParameter(
                name="SWXP_" + i,
                value=swxp,
                description="Solar wind power-law index",
                parameter_type="float",
                frozen=frozen,
            )
        )
        self.add_param(
            prefixParameter(
                name="SWXR1_" + i,
                units="MJD",
                description="Beginning of SWX interval",
                parameter_type="MJD",
                time_scale="utc",
                value=mjd_start,
            )
        )
        self.add_param(
            prefixParameter(
                name="SWXR2_" + i,
                units="MJD",
                description="End of SWX interval",
                parameter_type="MJD",
                time_scale="utc",
                value=mjd_end,
            )
        )
        self.setup()
        self.validate()
        return index

    def remove_swx_range(self, index):
        """Removes all SWX parameters associated with a given index/list of indices.

        Parameters
        ----------

        index : float, int, list, np.ndarray
            Number or list/array of numbers corresponding to SWX indices to be removed from model.
        """

        if (
            isinstance(index, int)
            or isinstance(index, float)
            or isinstance(index, np.int64)
        ):
            indices = [index]
        elif isinstance(index, (list, np.ndarray)):
            indices = index
        else:
            raise TypeError(
                f"index must be a float, int, list, or array - not {type(index)}"
            )
        for index in indices:
            index_rf = f"{int(index):04d}"
            for prefix in ["SWX_", "SWXP_", "SWXR1_", "SWXR2_"]:
                self.remove_param(prefix + index_rf)
        self.validate()

    def get_indices(self):
        """Returns an array of integers corresponding to SWX parameters.

        Returns
        -------
        inds : np.ndarray
            Array of SWX indices in model.
        """
        inds = []
        for p in self.params:
            if "SWX_" in p:
                inds.append(int(p.split("_")[-1]))
        return np.array(inds)

    def setup(self):
        super().setup()
        # Get SWX mapping.
        # Register the SWX derivatives
        for prefix_par in self.get_params_of_type("prefixParameter"):
            if prefix_par.startswith("SWX_"):
                # check to make sure power-law index is present
                # if not, put in default
                p_name = "SWXP_" + pint.utils.split_prefixed_name(prefix_par)[1]
                if not hasattr(self, p_name):
                    self.add_param(
                        prefixParameter(
                            name=p_name,
                            value=2,
                            description="Solar wind power-law index",
                            parameter_type="float",
                        )
                    )
                self.register_deriv_funcs(self.d_delay_d_swx, prefix_par)
                self.register_dm_deriv_funcs(self.d_dm_d_swx, prefix_par)
            elif prefix_par.startswith("SWXP_"):
                self.register_deriv_funcs(self.d_delay_d_swxp, prefix_par)
                self.register_dm_deriv_funcs(self.d_dm_d_swxp, prefix_par)

    def validate(self):
        """Validate the SWX parameters."""
        super().validate()
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        SWXR2_mapping = self.get_prefix_mapping_component("SWXR2_")
        if SWX_mapping.keys() != SWXP_mapping.keys():
            # FIXME: report mismatch
            raise ValueError(
                "SWX_ parameters do not "
                "match SWXP_ parameters. "
                "Please check your prefixed parameters."
            )
        if SWX_mapping.keys() != SWXR1_mapping.keys():
            # FIXME: report mismatch
            raise ValueError(
                "SWX_ parameters do not "
                "match SWXR1_ parameters. "
                "Please check your prefixed parameters."
            )
        if SWX_mapping.keys() != SWXR2_mapping.keys():
            raise ValueError(
                "SWX_ parameters do not "
                "match SWXR2_ parameters. "
                "Please check your prefixed parameters."
            )

    def validate_toas(self, toas):
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        SWXR2_mapping = self.get_prefix_mapping_component("SWXR2_")
        bad_parameters = []
        for k in SWXR1_mapping.keys():
            if self._parent[SWX_mapping[k]].frozen:
                continue
            b = self._parent[SWXR1_mapping[k]].quantity.mjd * u.d
            e = self._parent[SWXR2_mapping[k]].quantity.mjd * u.d
            mjds = toas.get_mjds()
            n = np.sum((b <= mjds) & (mjds < e))
            if n == 0:
                bad_parameters.append(SWX_mapping[k])
        if bad_parameters:
            raise MissingTOAs(bad_parameters)

    def swx_dm(self, toas):
        """Return solar wind DM for given TOAs"""
        condition = {}
        p = {}
        tbl = toas.table
        if not hasattr(self, "swx_toas_selector"):
            self.swx_toas_selector = TOASelect(is_range=True)
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        SWXR2_mapping = self.get_prefix_mapping_component("SWXR2_")
        for epoch_ind in SWX_mapping.keys():
            r1 = getattr(self, SWXR1_mapping[epoch_ind]).quantity
            r2 = getattr(self, SWXR2_mapping[epoch_ind]).quantity
            condition[SWX_mapping[epoch_ind]] = (r1.mjd, r2.mjd)
            p[SWX_mapping[epoch_ind]] = getattr(self, SWXP_mapping[epoch_ind]).value
        select_idx = self.swx_toas_selector.get_select_index(
            condition, tbl["mjd_float"]
        )
        # Get SWX delays
        dm = np.zeros(len(tbl)) * self._parent.DM.units
        for k, v in select_idx.items():
            ne_sw = getattr(self, k).quantity
            if len(v) > 0:
                dm[v] += (self.solar_wind_geometry(toas[v], p=p[k]) * ne_sw).to(
                    u.pc / u.cm**3
                )
        return dm

    def swx_delay(self, toas, acc_delay=None):
        """This is a wrapper function for interacting with the TimingModel class"""
        return self.dispersion_type_delay(toas)

    def d_dm_d_swx(self, toas, param_name, acc_delay=None):
        condition = {}
        tbl = toas.table
        if not hasattr(self, "swx_toas_selector"):
            self.swx_toas_selector = TOASelect(is_range=True)
        param = getattr(self, param_name)
        swx_index = param.index
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        SWXR2_mapping = self.get_prefix_mapping_component("SWXR2_")
        p = getattr(self, SWXP_mapping[swx_index]).value
        r1 = getattr(self, SWXR1_mapping[swx_index]).quantity
        r2 = getattr(self, SWXR2_mapping[swx_index]).quantity
        condition = {param_name: (r1.mjd, r2.mjd)}
        select_idx = self.swx_toas_selector.get_select_index(
            condition, tbl["mjd_float"]
        )

        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = tbl["freq"]
        deriv = np.zeros(len(tbl)) * u.pc
        for k, v in select_idx.items():
            if len(v) > 0:
                deriv[v] += self.solar_wind_geometry(toas[v], p=p)
        return deriv

    def d_delay_d_swx(self, toas, param_name, acc_delay=None):
        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = toas.table["freq"]
        deriv = self.d_delay_d_dmparam(toas, param_name)
        deriv[bfreq < 1.0 * u.MHz] = 0.0
        return deriv

    def d_dm_d_swxp(self, toas, param_name, acc_delay=None):
        condition = {}
        tbl = toas.table
        # still use the SWX selectors
        if not hasattr(self, "swx_toas_selector"):
            self.swx_toas_selector = TOASelect(is_range=True)
        param = getattr(self, param_name)
        swxp_index = param.index
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        SWXR2_mapping = self.get_prefix_mapping_component("SWXR2_")
        swx = getattr(self, SWX_mapping[swxp_index]).quantity
        p = getattr(self, SWXP_mapping[swxp_index]).value
        r1 = getattr(self, SWXR1_mapping[swxp_index]).quantity
        r2 = getattr(self, SWXR2_mapping[swxp_index]).quantity

        swx_name = "SWX_" + pint.utils.split_prefixed_name(param_name)[1]
        condition = {swx_name: (r1.mjd, r2.mjd)}
        select_idx = self.swx_toas_selector.get_select_index(
            condition, tbl["mjd_float"]
        )

        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = tbl["freq"]
        deriv = np.zeros(len(tbl)) * u.pc / u.cm**3
        for k, v in select_idx.items():
            if len(v) > 0:
                deriv[v] += swx * self.d_solar_wind_geometry_d_swxp(toas[v], p=p)
        return deriv

    def d_delay_d_swxp(self, toas, param_name, acc_delay=None):
        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = toas.table["freq"]
        deriv = self.d_delay_d_dmparam(toas, param_name)
        deriv[bfreq < 1.0 * u.MHz] = 0.0
        return deriv

    def print_par(self, format="pint"):
        result = ""
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        SWXR2_mapping = self.get_prefix_mapping_component("SWXR2_")
        sorted_list = sorted(SWX_mapping.keys())
        for ii in sorted_list:
            result += getattr(self, SWX_mapping[ii]).as_parfile_line(format=format)
            result += getattr(self, SWXP_mapping[ii]).as_parfile_line(format=format)
            result += getattr(self, SWXR1_mapping[ii]).as_parfile_line(format=format)
            result += getattr(self, SWXR2_mapping[ii]).as_parfile_line(format=format)
        return result

    def get_max_dms(self):
        """Return approximate maximum DMs for each segment from the Solar Wind (at conjunction)

        Simplified model that assumes a circular orbit

        Returns
        -------
        astropy.quantity.Quantity
        """
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        sorted_list = sorted(SWX_mapping.keys())
        dms = np.zeros(len(sorted_list)) * u.pc / u.cm**3
        coord = self._parent.get_psr_coords()
        for j, ii in enumerate(sorted_list):
            r1 = getattr(self, SWXR1_mapping[ii]).quantity
            p = getattr(self, SWXP_mapping[ii]).value
            swx = getattr(self, SWX_mapping[ii]).quantity
            t0, elongation = pint.utils.get_conjunction(coord, r1, precision="high")
            theta = elongation
            r = 1 * u.AU
            # impact parameter
            b = r * np.sin(theta)
            # distance from the Earth to the impact point
            z_sun = r * np.cos(theta)
            # a big value for comparison
            # this is what Enterprise uses
            z_p = (1e14 * u.s * const.c).to(b.unit)
            if p > 1:
                solar_wind_geometry = (
                    (1 / b.to_value(u.AU)) ** p
                    * b
                    * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
                )
            else:
                raise NotImplementedError(
                    "Solar Dispersion Delay not implemented for power-law index p <= 1"
                )
            dms[j] = (solar_wind_geometry * swx).to(u.pc / u.cm**3)
        return dms

    def get_min_dms(self):
        """Return approximate minimum DMs for each segment from the Solar Wind (at conjunction)

        Simplified model that assumes a circular orbit

        Returns
        -------
        astropy.quantity.Quantity
        """
        SWX_mapping = self.get_prefix_mapping_component("SWX_")
        SWXP_mapping = self.get_prefix_mapping_component("SWXP_")
        SWXR1_mapping = self.get_prefix_mapping_component("SWXR1_")
        sorted_list = sorted(SWX_mapping.keys())
        dms = np.zeros(len(sorted_list)) * u.pc / u.cm**3
        coord = self._parent.get_psr_coords()
        for j, ii in enumerate(sorted_list):
            r1 = getattr(self, SWXR1_mapping[ii]).quantity
            p = getattr(self, SWXP_mapping[ii]).value
            swx = getattr(self, SWX_mapping[ii]).quantity
            t0, elongation = pint.utils.get_conjunction(coord, r1, precision="high")
            # for the min
            theta = 180 * u.deg - elongation
            r = 1 * u.AU
            # impact parameter
            b = r * np.sin(theta)
            # distance from the Earth to the impact point
            z_sun = r * np.cos(theta)
            # a big value for comparison
            # this is what Enterprise uses
            z_p = (1e14 * u.s * const.c).to(b.unit)
            if p > 1:
                solar_wind_geometry = (
                    (1 / b.to_value(u.AU)) ** p
                    * b
                    * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
                )
            else:
                raise NotImplementedError(
                    "Solar Dispersion Delay not implemented for power-law index p <= 1"
                )
            dms[j] = (solar_wind_geometry * swx).to(u.pc / u.cm**3)
        return dms


class SolarWindDispersionScaled(Dispersion):
    """Dispersion due to the solar wind (basic model).

    The model is a simple spherically-symmetric model that is fit
    in its constant amplitude and power-law index

    Parameters supported:

    .. paramtable::
        :class: pint.models.solar_wind_dispersion.SolarWindDispersionScaled

    References
    ----------
    - Edwards et al. 2006, MNRAS, 372, 1549; Setion 2.5.4
    - Madison et al. 2019, ApJ, 872, 150; Section 3.1.
    - Hazboun et al. (2022, ApJ, 929, 39)
    - You et al. (2012, MNRAS, 422, 1160)
    """

    register = True
    category = "solar_wind"

    def __init__(self):
        super().__init__()
        self.add_param(
            floatParameter(
                name="SWDMMAX", units="pc*cm^-3", value=0.0, description="Maximum DM"
            )
        )
        self.add_param(
            floatParameter(
                name="SWPP",
                value=2.0,
                units="",
                description="Solar Wind Model radial power-law index",
            )
        )
        self.dm_value_funcs += [self.solar_wind_dm]
        self.delay_funcs_component += [self.solar_wind_delay]
        self.set_special_params(["SWDMMAX", "SWPP"])

    def setup(self):
        super().setup()
        self.register_dm_deriv_funcs(self.d_dm_d_swdmmax, "SWDMMAX")
        self.register_deriv_funcs(self.d_delay_d_swdmmax, "SWDMMAX")
        self.register_dm_deriv_funcs(self.d_dm_d_swp, "SWPP")
        self.register_deriv_funcs(self.d_delay_d_swp, "SWPP")

    def solar_wind_geometry(self, toas):
        """Return the geometry of solar wind dispersion.

        Parameters
        ----------
        toas : pint.toa.TOAs

        Returns
        -------
        astropy.quantity.Quantity
        """
        p = self.SWPP.value

        # get elongation angle, distance from Earth to Sun
        theta, r = self._parent.sun_angle(toas, also_distance=True)
        # impact parameter
        b = r * np.sin(theta)
        # distance from the Earth to the impact point
        z_sun = r * np.cos(theta)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b.unit)
        if p > 1:
            solar_wind_geometry = (
                (1 / b.to_value(u.AU)) ** p
                * b
                * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
            )
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for power-law index p <= 1"
            )
        return solar_wind_geometry.to(u.pc)

    def fiducial_solar_wind_geometry(self):
        """Return the geometry of solar wind dispersion for the fiducial elongation

        Returns
        -------
        astropy.quantity.Quantity
        """
        p = self.SWPP.value
        r0 = 1 * u.AU
        coord = self._parent.get_psr_coords()
        theta0 = coord.transform_to(pint.pulsar_ecliptic.PulsarEcliptic()).lat

        # impact parameter
        b = r0 * np.sin(theta0)
        # distance from the Earth to the impact point
        z_sun = r0 * np.cos(theta0)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b.unit)
        if p > 1:
            solar_wind_geometry = (
                (1 / b.to_value(u.AU)) ** p
                * b
                * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
            )
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for power-law index p <= 1"
            )
        return solar_wind_geometry.to(u.pc)

    def solar_wind_dm(self, toas):
        """Return the solar wind dispersion measure."""
        solar_wind_geometry = self.solar_wind_geometry(toas)
        fiducial_solar_wind_geometry = self.fiducial_solar_wind_geometry()
        solar_wind_dm = self.SWDMMAX.quantity * (
            solar_wind_geometry / fiducial_solar_wind_geometry
        )
        return solar_wind_dm.to(u.pc / u.cm**3)

    def solar_wind_delay(self, toas, acc_delay=None):
        """This is a wrapper function to compute solar wind dispersion delay."""
        if self.SWDMMAX.value == 0:
            return np.zeros(len(toas)) * u.s
        return self.dispersion_type_delay(toas)

    def d_dm_d_swdmmax(self, toas, param_name, acc_delay=None):
        """Derivative of of DM wrt the solar wind max dm"""
        return self.solar_wind_geometry(toas) / self.fiducial_solar_wind_geometry()

    def d_delay_d_swdmmax(self, toas, param_name, acc_delay=None):
        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = toas.table["freq"]
        deriv = self.d_delay_d_dmparam(toas, "SWDMMAX")
        deriv[bfreq < 1.0 * u.MHz] = 0.0
        return deriv

    def d_solar_wind_geometry_d_swp(self, toas, param_name, acc_delay=None):
        """Derivative of solar_wind_geometry (path length) wrt power-law index p

        The evaluation is done using Eqn. 12 in Hazboun et al. (2022).  The first term
        involving hypergeometric functions (:func:`_hypergeom_function`)
        has the derivative computed approximately using a Pade expansion (:func:`_d_hypergeom_function_dp`).
        The second uses gamma functions (:func:`_gamma_function`) and has the derivative computed
        using polygamma functions (:func:`_d_gamma_function_dp`).

        """

        # get elongation angle, distance from Earth to Sun
        theta, r = self._parent.sun_angle(toas, also_distance=True)
        # impact parameter
        b = r * np.sin(theta)
        # distance from the Earth to the impact point
        z_sun = r * np.cos(theta)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b.unit)
        p = self.SWPP.value
        if p > 1:
            return (1 / b.to_value(u.AU)) ** p * (
                b * _d_hypergeom_function_dp(b, z_sun, p)
                + (b * np.sqrt(np.pi) / 2) * _d_gamma_function_dp(p)
            ) - (1 / b.to_value(u.AU)) ** p * np.log(b.to_value(u.AU)) * (
                b * _hypergeom_function(b, z_sun, p)
                + (b * np.sqrt(np.pi) / 2) * _gamma_function(p)
            )
        else:
            return np.inf * np.ones(len(toas)) * u.pc

    def d_fiducial_solar_wind_geometry_d_swp(self, toas, param_name, acc_delay=None):
        """Derivative of fiducial_solar_wind_geometry (path length) wrt power-law index p

        The evaluation is done using Eqn. 12 in Hazboun et al. (2022).  The first term
        involving hypergeometric functions (:func:`_hypergeom_function`)
        has the derivative computed approximately using a Pade expansion (:func:`_d_hypergeom_function_dp`).
        The second uses gamma functions (:func:`_gamma_function`) and has the derivative computed
        using polygamma functions (:func:`_d_gamma_function_dp`).

        """
        # fiducial values
        r0 = 1 * u.AU
        coord = self._parent.get_psr_coords()
        theta0 = coord.transform_to(pint.pulsar_ecliptic.PulsarEcliptic()).lat
        b0 = r0 * np.sin(theta0)
        # distance from the Earth to the impact point
        z_sun0 = r0 * np.cos(theta0)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b0.unit)
        p = self.SWPP.value
        if p > 1:
            return (1 / b0.to_value(u.AU)) ** p * (
                b0 * _d_hypergeom_function_dp(b0, z_sun0, p)
                + (b0 * np.sqrt(np.pi) / 2) * _d_gamma_function_dp(p)
            ) - (1 / b0.to_value(u.AU)) ** p * np.log(b0.to_value(u.AU)) * (
                b0 * _hypergeom_function(b0, z_sun0, p)
                + (b0 * np.sqrt(np.pi) / 2) * _gamma_function(p)
            )
        else:
            return np.inf * np.ones(len(toas)) * u.pc

    def d_dm_d_swp(self, toas, param_name, acc_delay=None):
        geometry = self.solar_wind_geometry(toas)
        fiducial_geometry = self.fiducial_solar_wind_geometry()
        d_geometry_dp = self.d_solar_wind_geometry_d_swp(
            toas, param_name, acc_delay=acc_delay
        )
        d_fiducial_geometry_dp = self.d_fiducial_solar_wind_geometry_d_swp(
            toas, param_name, acc_delay=acc_delay
        )
        return self.SWDMMAX.quantity * (
            (d_geometry_dp / fiducial_geometry)
            - (geometry / fiducial_geometry**2) * d_fiducial_geometry_dp
        )

    def d_delay_d_swp(self, toas, param_name, acc_delay=None):
        try:
            bfreq = self._parent.barycentric_radio_freq(toas)
        except AttributeError:
            warn("Using topocentric frequency for dedispersion!")
            bfreq = toas.table["freq"]
        deriv = self.d_delay_d_dmparam(toas, "SWPP")
        deriv[bfreq < 1.0 * u.MHz] = 0.0
        return deriv

    def print_par(self, format="pint"):
        result = ""
        result += getattr(self, "SWDMMAX").as_parfile_line(format=format)
        result += getattr(self, "SWPP").as_parfile_line(format=format)
        return result

    def get_max_dm(self):
        """Return approximate maximum DM from the Solar Wind (at conjunction)

        Simplified model that assumes a circular orbit

        Returns
        -------
        astropy.quantity.Quantity
        """
        return self.SWDMMAX.quantity

    def get_min_dm(self):
        """Return approximate minimum DM from the Solar Wind (180deg away from conjunction)

        Simplified model that assumes a circular orbit

        Returns
        -------
        astropy.quantity.Quantity
        """
        p = self.SWPP.value
        # for the max
        coord = self._parent.get_psr_coords()
        theta0 = coord.transform_to(pint.pulsar_ecliptic.PulsarEcliptic()).lat
        # for the min
        theta = (
            np.array([(180 * u.deg - theta0).to_value(u.deg), theta0.to_value(u.deg)])
            * u.deg
        )
        r = 1 * u.AU
        # impact parameter
        b = r * np.sin(theta)
        # distance from the Earth to the impact point
        z_sun = r * np.cos(theta)
        # a big value for comparison
        # this is what Enterprise uses
        z_p = (1e14 * u.s * const.c).to(b.unit)
        if p > 1:
            solar_wind_geometry = (
                (1 / b.to_value(u.AU)) ** p
                * b
                * (_dm_p_int(b, z_p, p) - _dm_p_int(b, -z_sun, p))
            )
        else:
            raise NotImplementedError(
                "Solar Dispersion Delay not implemented for power-law index p <= 1"
            )
        return (
            (solar_wind_geometry[0] / solar_wind_geometry[1]) * self.SWDMMAX.quantity
        ).to(u.pc / u.cm**3)

    def get_ne_sw(self):
        """Return the effective Solar Wind electron density at 1 AU

        Returns
        -------
        astropy.quantity.Quantity
        """
        return (self.SWDMMAX.quantity / self.fiducial_solar_wind_geometry()).to(
            u.cm**-3
        )
