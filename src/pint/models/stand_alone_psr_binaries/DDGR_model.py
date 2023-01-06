"""The DDGR model - Damour and Deruelle with GR assumed"""
import astropy.constants as c
import astropy.units as u
import numpy as np
import warnings
from loguru import logger as log

from .DD_model import DDmodel


@u.quantity_input(M1=u.Msun, M2=u.Msun, n=1 / u.d)
def _solve_kepler(M1, M2, n, ARTOL=1e-10):
    """Relativistic version of Kepler's third law, solved by iteration

    Taylor & Weisberg (1989), Eqn. 15
    In tempo, implemented as ``mass2dd`` (https://sourceforge.net/p/tempo/tempo/ci/master/tree/src/mass2dd.f)


    Parameters
    ----------
    M1 : astropy.units.Quantity
        Mass of pulsar
    M2 : astropy.units.Quantity
        Mass of companion
    n : astropy.units.Quantity
        orbital angular frequency
    ARTOL : float
        fractional tolerance for solution

    Returns
    -------
    arr0 : astropy.units.Quantity
        non-relativistic semi-major axis
    arr : astropy.units.Quantity
        relativstic semi-major axis
    """
    MTOT = M1 + M2
    # initial NR value
    arr0 = (c.G * MTOT / n**2) ** (1.0 / 3)
    arr = arr0
    arr_old = arr
    arr = arr0 * (
        1 + (M1 * M2 / MTOT**2 - 9) * (c.G * MTOT / (2 * arr * c.c**2))
    ) ** (2.0 / 3)
    # iterate to get correct value
    while np.fabs((arr - arr_old) / arr) > ARTOL:
        arr_old = arr
        ar = arr0 * (
            1 + (M1 * M2 / MTOT**2 - 9) * (c.G * MTOT / (2 * arr * c.c**2))
        ) ** (2.0 / 3)

    return arr0.decompose(), arr.decompose()


class DDGRmodel(DDmodel):
    """Damour and Deruelle model assuming GR to be correct

    It supports all the parameters defined in :class:`pint.models.pulsar_binary.PulsarBinary`
    and :class:`pint.models.binary_dd.BinaryDD` plus:

        MTOT
            Total mass
        XPBDOT
            Excess PBDOT beyond what GR predicts
        XOMDOT
            Excess OMDOT beyond what GR predicts

    It also reads but ignores:

        SINI
        PBDOT
        OMDOT
        GAMMA
        DR
        DTH

    Parameters supported:

    .. paramtable::
        :class: pint.models.binary_dd.BinaryDDGR

    References
    ----------
    - Taylor and Weisberg (1989), ApJ, 345, 434 [1]_

    .. [1] https://ui.adsabs.harvard.edu/abs/1989ApJ...345..434T/abstract
    """

    def __init__(self, t=None, input_params=None):
        super().__init__()
        self.binary_name = "DDS"
        self.param_default_value.update(
            {"MTOT": 2.8 * u.Msun, "XOMDOT": 0 * u.deg / u.yr, "XPBDOT": 0 * u.s / u.s}
        )

        # If any parameter has aliases, it should be updated
        # self.param_aliases.update({})
        self.binary_params = list(self.param_default_value.keys())
        # Remove unused parameter SINI and others
        for p in ["SINI", "PBDOT", "OMDOT", "GAMMA", "DR", "DTH"]:
            del self.param_default_value[p]
        self.set_param_values()
        if input_params is not None:
            self.update_input(param_dict=input_params)

    def _updatePK(self, ARTOL=1e-10):
        """Update measurable PK quantities from system parameters for DDGR model

        Taylor & Weisberg (1989), Eqn. 15-25
        In tempo, implemented as ``mass2dd`` (https://sourceforge.net/p/tempo/tempo/ci/master/tree/src/mass2dd.f)

        Parameters
        ----------
        ARTOL : float
            fractional tolerance for solution of relativistic Kepler equation (passed to :func:`_solve_kepler`)

        """
        # if not all of the required parameters have been set yet (e.g., while initializing)
        # don't do anything
        for p in ["PB", "ECC", "M2", "MTOT", "A1"]:
            if not hasattr(self, p) or getattr(self, p).value is None:
                return

        # unclear if this should compute the PB in a different way
        # since this could incorporate changes, but to determine those changes we need to run this function
        PB = self.PB.to(u.s)
        self._M1 = self.MTOT - self.M2
        self._n = 2 * np.pi / PB
        arr0, arr = _solve_kepler(self._M1, self.M2, self._n, ARTOL=ARTOL)
        self._arr = arr
        # pulsar component of semi-major axis
        self._ar = self._arr * (self.M2 / self.MTOT)
        # Taylor & Weisberg (1989), Eqn. 20
        self._SINI = (self.a1() / self._ar).decompose()
        # Taylor & Weisberg (1989), Eqn. 17
        # use arr0 here following comments in tempo
        self._GAMMA = (
            self.ecc()
            * c.G
            * self.M2
            * (self._M1 + 2 * self.M2)
            / (self._n * c.c**2 * arr0 * self.MTOT)
        ).to(u.s)
        # Taylor & Weisberg (1989), Eqn. 18
        self._PBDOT = (
            (-192 * np.pi / (5 * c.c**5))
            * (c.G * self._n) ** (5.0 / 3)
            * self._M1
            * self.M2
            * self.MTOT ** (-1.0 / 3)
            * self.fe
        ).decompose()
        # we calculate this here although we don't need it for DDGR
        self._OMDOT = (
            3
            * (self._n) ** (5.0 / 3)
            * (1 / (1 - self.ecc() ** 2))
            * (c.G * (self._M1 + self.M2) / c.c**3) ** (2.0 / 3)
        ).to(u.deg / u.yr, equivalencies=u.dimensionless_angles())
        # Taylor & Weisberg (1989), Eqn. 16
        # use arr0 here following comments in tempo
        self._k = (
            (3 * c.G * self.MTOT) / (c.c**2 * arr0 * (1 - self.ecc() ** 2))
        ).decompose()
        # Taylor & Weisberg (1989), Eqn. 24
        self._DR = (
            (c.G / (c.c**2 * self.MTOT * self._arr))
            * (3 * self._M1**2 + 6 * self._M1 * self.M2 + 2 * self.M2**2)
        ).decompose()
        # Damour & Deruelle (1986), Eqn. 36
        self._er = self.ecc() * (1 + self._DR)
        # Taylor & Weisberg (1989), Eqn. 25
        self._DTH = (
            (c.G / (c.c**2 * self.MTOT * self._arr))
            * (3.5 * self._M1**2 + 6 * self._M1 * self.M2 + 2 * self.M2**2)
        ).decompose()
        # Damour & Deruelle (1986), Eqn. 37
        self._eth = self.ecc() * (1 + self._DTH)

    @property
    def fe(self):
        # Taylor & Weisberg (1989), Eqn. 19
        return (1 + (73.0 / 24) * self.ecc() ** 2 + (37.0 / 96) * self.ecc() ** 4) * (
            1 - self.ecc() ** 2
        ) ** (-7.0 / 2)

    ####################
    @property
    def k(self):
        """Precessing rate assuming GR

        Taylor and Weisberg (1989), Eqn. 16
        """
        return self._k

    def d_k_d_MTOT(self):
        return (
            2
            * (c.G**2 * self._n**2 / self.MTOT) ** (1.0 / 3)
            / c.c**2
            / (1 - self.ecc() ** 2)
        )

    def d_k_d_ECC(self):
        return (
            6
            * (c.G * self.MTOT * self._n) ** (2.0 / 3)
            * self.ecc()
            / (c.c**2 * (1 - self.ecc() ** 2) ** 2)
        )

    def d_k_d_PB(self):
        return (
            2
            * (4 * np.pi**2 * c.G**2 * self.MTOT**2 / self.PB**5) ** (1.0 / 3)
            / c.c**2
            / (self.ecc() ** 2 - 1)
        )

    def d_k_d_par(self, par):
        par_obj = getattr(self, par)
        try:
            ko_func = getattr(self, f"d_k_d_{par}")
        except AttributeError:
            ko_func = lambda: np.zeros(len(self.tt0)) * u.Unit("") / par_obj.unit
        return ko_func()

    ####################
    def omega(self):
        # add in any excess OMDOT from the XOMDOT term
        return (
            self.OM
            + self.nu() * self.k
            + self.nu() * (self.XOMDOT / (2 * np.pi * u.rad / self.PB))
        ).to(u.rad)

    def d_omega_d_XOMDOT(self):
        """Derivative.

        Calculates::

            dOmega/dXOMDOT = 1/n*nu
            n = 2*pi/PB
            dOmega/dXOMDOT = PB/2*pi*nu
        """
        return self.nu() * self.pb().to(u.s) / (2 * np.pi * u.rad)

    ####################
    @property
    def SINI(self):
        return self._SINI

    def d_SINI_d_MTOT(self):
        return (
            (2.0 / 3)
            * self.a1()
            * (self._n**2 / c.G / self.MTOT) ** (1.0 / 3)
            / self.M2
        )

    def d_SINI_d_M2(self):
        return (
            -(self.a1() * (self.MTOT**2 * self._n**2 / c.G) ** (1.0 / 3))
            / self.M2**2
        )

    def d_SINI_d_PB(self):
        return (
            -2
            * self.a1()
            * (4 * np.pi**2 * self.MTOT**2 / c.G / self.PB**5) ** (1.0 / 3)
            / 3
            / self.M2
        )

    def d_SINI_d_A1(self):
        return (self.MTOT**2 * self._n**2 / c.G) ** (1.0 / 3) / self.M2

    def d_SINI_d_par(self, par):
        par_obj = getattr(self, par)
        try:
            ko_func = getattr(self, f"d_SINI_d_{par}")
        except AttributeError:
            ko_func = lambda: np.zeros(len(self.tt0)) * u.Unit("") / par_obj.unit
        return ko_func()

    ####################
    @property
    def GAMMA(self):
        return self._GAMMA

    def d_GAMMA_d_ECC(self):
        return (c.G ** (2.0 / 3) * self.M2 * (self.MTOT + self.M2)) / (
            c.c**2 * self.MTOT ** (4.0 / 3) * self._n ** (1.0 / 3)
        )

    def d_GAMMA_d_MTOT(self):
        return (
            -self.M2
            * self.ecc()
            * c.G ** (2.0 / 3)
            * (self.MTOT + 4 * self.M2)
            / (3 * self.MTOT ** (7.0 / 3) * c.c**2 * self._n ** (1.0 / 3))
        )

    def d_GAMMA_d_M2(self):
        return (
            self.ecc()
            * c.G ** (2.0 / 3)
            * (self.MTOT + 2 * self.M2)
            / (c.c**2 * self.MTOT ** (4.0 / 3) * self._n ** (1.0 / 3))
        )

    def d_GAMMA_d_PB(self):
        return (
            self.ecc()
            * (c.G**2 * 4 / np.pi / self.MTOT**4 / self.PB**2) ** (1.0 / 3)
            * self.M2
            * (self.MTOT + self.M2)
            / 6
            / c.c**2
        )

    def d_GAMMA_d_par(self, par):
        par_obj = getattr(self, par)
        try:
            ko_func = getattr(self, f"d_GAMMA_d_{par}")
        except AttributeError:
            ko_func = lambda: np.zeros(len(self.tt0)) * u.s / par_obj.unit
        return ko_func()

    ####################
    @property
    def PBDOT(self):
        # don't add XPBDOT here: that is handled by the normal binary objects
        return self._PBDOT

    def d_PBDOT_d_MTOT(self):
        return (
            -(64 * np.pi / 5 / c.c**5)
            * (c.G**5 * self._n**5 / self.MTOT**4) ** (1.0 / 3)
            * self.M2
            * self.fe
            * (2 * self.MTOT + self.M2)
        )

    def d_PBDOT_d_M2(self):
        return (
            -(192 * np.pi / 5 / c.c**5)
            * (c.G**5 * self._n**5 / self.MTOT) ** (1.0 / 3)
            * self.fe
            * (self.MTOT - 2 * self.M2)
        )

    def d_PBDOT_d_ECC(self):
        return (
            -(222 * np.pi / 5 / c.c**5)
            * self.ecc()
            * (c.G**5 * self._n**5 / self.MTOT) ** (1.0 / 3)
            * self.M2
            * (self.MTOT - self.M2)
            * (self.ecc() ** 4 + (536.0 / 37) * self.ecc() ** 2 + 1256.0 / 111)
            / (1 - self.ecc() ** 2) ** (9.0 / 2)
        )

    def d_PBDOT_d_PB(self):
        return (
            128
            * self.fe
            * (4 * c.G**5 * np.pi**8 / self.PB**8 / self.MTOT) ** (1.0 / 3)
            * (self.MTOT - self.M2)
            / c.c**5
        )

    def d_PBDOT_d_XPBDOT(self):
        return np.ones(len(self.tt0)) * u.Unit("")

    def d_PBDOT_d_par(self, par):
        par_obj = getattr(self, par)
        try:
            ko_func = getattr(self, f"d_PBDOT_d_{par}")
        except AttributeError:
            ko_func = lambda: np.zeros(len(self.tt0)) * u.Unit("") / par_obj.unit
        return ko_func()

    ####################
    @property
    def OMDOT(self):
        # don't need an explicit OMDOT here since the main precession is carried in the k term
        return self.XOMDOT

    def d_OMDOT_d_par(self, par):
        par_obj = getattr(self, par)
        if par == "XOMDOT":
            return lambda: np.ones(len(self.tt0)) * (u.deg / u.yr) / par_obj.unit
        else:
            return lambda: np.zeros(len(self.tt0)) * (u.deg / u.yr) / par_obj.unit

    ####################
    @property
    def DR(self):
        return self._DR

    def d_DR_d_MTOT(self):
        return (
            2
            * (c.G**2 * self._n**2 / self.MTOT**7) ** (1.0 / 3)
            * (self.MTOT**2 + 2 * self.M2**2 / 3)
            / c.c**2
        )

    def d_DR_d_M2(self):
        return -2 * (c.G * self._n / self.MTOT**2) ** (2.0 / 3) * self.M2 / c.c**2

    def d_DR_d_PB(self):
        return (
            -2
            * (4 * np.pi**2 * c.G**2 / self.MTOT**4 / self.PB**5) ** (1.0 / 3)
            * (self.MTOT**2 - self.M2**2 / 3)
            / c.c**2
        )

    def d_DR_d_par(self, par):
        par_obj = getattr(self, par)
        try:
            ko_func = getattr(self, f"d_DR_d_{par}")
        except AttributeError:
            ko_func = lambda: np.zeros(len(self.tt0)) * u.Unit("") / par_obj.unit
        return ko_func()

    ####################
    @property
    def DTH(self):
        return self._DTH

    def d_DTH_d_M(self):
        return (
            (c.G**2 * self._n**2 / self.MTOT**7) ** (1.0 / 3)
            * (7 * self.MTOT**2 + self.MTOT * self.M2 + 2 * self.M2**2)
            / 3
            / c.c**2
        )

    def d_DTH_d_M2(self):
        return (
            -((c.G * self._n / self.MTOT**2) ** (2.0 / 3))
            * (self.MTOT + self.M2)
            / c.c**2
        )

    def d_DTH_d_PB(self):
        return (
            (4 * np.pi**2 * c.G**2 / self.MTOT**4 / self.PB**5) ** (1.0 / 3)
            * (-7 * self.MTOT**2 + 2 * self.MTOT * self.M2 + self.M2**2)
            / 3
            / c.c**2
        )

    def d_DTH_d_par(self, par):
        par_obj = getattr(self, par)
        try:
            ko_func = getattr(self, f"d_DTH_d_{par}")
        except AttributeError:
            ko_func = lambda: np.zeros(len(self.tt0)) * u.Unit("") / par_obj.unit
        return ko_func()

    def er(self):
        return self._er

    def eTheta(self):
        return self._eth

    @SINI.setter
    def SINI(self, val):
        log.debug(
            "DDGR model uses MTOT to derive the inclination angle. SINI will not be used."
        )

    @PBDOT.setter
    def PBDOT(self, val):
        log.debug("DDGR model uses MTOT to derive PBDOT. PBDOT will not be used.")

    @OMDOT.setter
    def OMDOT(self, val):
        log.debug("DDGR model uses MTOT to derive OMDOT. OMDOT will not be used.")

    @GAMMA.setter
    def GAMMA(self, val):
        log.debug("DDGR model uses MTOT to derive GAMMA. GAMMA will not be used.")

    @DR.setter
    def DR(self, val):
        log.debug("DDGR model uses MTOT to derive Dr. Dr will not be used.")

    @DTH.setter
    def DTH(self, val):
        log.debug("DDGR model uses MTOT to derive Dth. Dth will not be used.")

    # wrap these properties so that we can update the PK calculations when they are set
    @property
    def PB(self):
        return self._PB

    @PB.setter
    def PB(self, val):
        self._PB = val
        self._updatePK()

    @property
    def MTOT(self):
        return self._MTOT

    @MTOT.setter
    def MTOT(self, val):
        self._MTOT = val
        self._updatePK()

    @property
    def M2(self):
        return self._M2

    @M2.setter
    def M2(self, val):
        self._M2 = val
        self._updatePK()

    @property
    def A1(self):
        return self._A1

    @A1.setter
    def A1(self, val):
        self._A1 = val
        self._updatePK()

    @property
    def ECC(self):
        return self._ECC

    @ECC.setter
    def ECC(self, val):
        self._ECC = val
        self._updatePK()

    @property
    def A1DOT(self):
        return self._A1DOT

    @A1DOT.setter
    def A1DOT(self, val):
        self._A1DOT = val
        self._updatePK()

    @property
    def EDOT(self):
        return self._EDOT

    @EDOT.setter
    def EDOT(self, val):
        self._EDOT = val
        self._updatePK()
