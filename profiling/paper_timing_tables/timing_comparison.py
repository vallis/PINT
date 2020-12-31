"""
A script for comparing the timing of PINT and TEMPO/Tempo2 for standard fitting 
cases. Recreates Tables 7, 8, and 9 from PINT paper.
Requires: 
    - TEMPO
    - TEMPO2 
*** THIS IS A PLACEHOLDER SCRIPT, final script will be in a notebook and cleaner/easier to work with. ***
"""
from pint import toa
from pint import models
from pint import fitter
import os
import sys
import subprocess
import timeit
import datetime
from astropy.table import Table
from astropy.io import ascii

MAXIT = 5  # number of iterations to time and average


def pintrun(parfile, timfile, ptime_arr, pickle, fitter):
    """ Runs and times pintempo 5 times and averages times, appending to a list. """
    gls = ""
    if fitter == "gls":
        gls = " --gls"
    usepickle = ""
    if pickle:
        usepickle = " --usepickle"
    for i in range(MAXIT):
        subprocess.call(
            "time -o pinttimes.txt -a pintempo"
            + usepickle
            + gls
            + " "
            + parfile
            + " "
            + timfile,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    pinttime = datetime.timedelta()  # defaults to 0
    with open("pinttimes.txt") as f:
        for line in f:
            if "user" in line:
                vals = line.split()
                timestr = vals[2][
                    :-7
                ]  # based on default format of time function output
                try:
                    t = datetime.datetime.strptime(
                        timestr, "%M:%S.%f"
                    ).time()  # format string into time obj
                except ValueError:
                    t = datetime.datetime.strptime(
                        timestr, "%H:%M:%S"
                    ).time()  # format string into time obj
                pinttime = pinttime + datetime.timedelta(
                    hour=t.hour,
                    minutes=t.minute,
                    seconds=t.second,
                    microseconds=t.microsecond,
                )  # running sum
    os.remove("pinttimes.txt")  # remove temporary storage file
    ptime_arr.append(pinttime.total_seconds() / MAXIT)  # averages time


def temporun(parfile, timfile, ttime_arr, fitter):
    """ Runs and times TEMPO 5 times and averages times, appending to a list. """
    fit = ""
    if fitter == "gls":
        fit = " -G"
    for i in range(MAXIT):
        subprocess.call(
            "time -o tempotimes.txt -a tempo"
            + fit
            + " -f "
            + parfile
            + " "
            + timfile
            + "",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    tempotime = datetime.timedelta()  # defaults to 0
    with open("tempotimes.txt") as f:
        for line in f:
            if "user" in line:
                vals = line.split()
                timestr = vals[2][:-7]  # based on default format of time function
                try:
                    t = datetime.datetime.strptime(
                        timestr, "%M:%S.%f"
                    ).time()  # format string into time obj
                except ValueError:
                    t = datetime.datetime.strptime(
                        timestr, "%H:%M:%S"
                    ).time()  # format string into time obj
                tempotime = tempotime + datetime.timedelta(
                    hour=t.hour,
                    minutes=t.minute,
                    seconds=t.second,
                    microseconds=t.microsecond,
                )  # running sum
    os.remove("tempotimes.txt")  # remove temporary storage file
    ttime_arr.append(tempotime.total_seconds() / MAXIT)  # average time


def tempo2run(parfile, timfile, t2time_arr):
    """ Runs and times Tempo2 5 times and averages times, appending to a list. """
    for i in range(MAXIT):
        subprocess.call(
            "time -o tempo2times.txt -a tempo2 -nobs 100003 -f "
            + parfile
            + " "
            + timfile
            + "",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    tempo2time = datetime.timedelta()  # defaults to 0
    with open("tempo2times.txt") as f:
        for line in f:
            if "user" in line:
                vals = line.split()
                timestr = vals[2][:-7]  # based on default format of time function
                try:
                    t = datetime.datetime.strptime(
                        timestr, "%M:%S.%f"
                    ).time()  # format string into time obj
                except ValueError:
                    t = datetime.datetime.strptime(
                        timestr, "%H:%M:%S"
                    ).time()  # format string into time obj
                tempo2time = tempo2time + datetime.timedelta(
                    hour=t.hour,
                    minutes=t.minute,
                    seconds=t.second,
                    microseconds=t.microsecond,
                )  # running sum
    os.remove("tempo2times.txt")  # remove temporary storage file
    t2time_arr.append(tempo2time.total_seconds() / MAXIT)  # average time


def getTimes(file, arr):
    """ Takes time output from a file and appends it to a list. """
    with open(file) as f:
        for line in f:
            arr.append(float(line) / MAXIT)  # average time
    os.remove(file)


if __name__ == "__main__":
    timfiles = [
        "NGC6440E_fake100.tim",
        "NGC6440E_fake1k.tim",
        "NGC6440E_fake10k.tim",
        "NGC6440E_fake100k.tim",
    ]

    # Generate simple, fake TOAs for the timing runs
    make_fake_TOA1 = "zima --startMJD 53478 --duration 700 --freq 1400 2000 --ntoa 100 NGC6440E.par NGC6440E_fake100.tim"
    make_fake_TOA2 = "zima --startMJD 53478 --duration 700 --freq 1400 2000 --ntoa 1000 NGC6440E.par NGC6440E_fake1k.tim"
    make_fake_TOA3 = "zima --startMJD 53478 --duration 700 --freq 1400 2000 --ntoa 10000 NGC6440E.par NGC6440E_fake10k.tim"
    make_fake_TOA4 = "zima --startMJD 53478 --duration 700 --freq 1400 2000 --ntoa 100000 NGC6440E.par NGC6440E_fake100k.tim"
    # call operations on command line
    print("Making fake TOAs...")
    subprocess.call(
        make_fake_TOA1, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.call(
        make_fake_TOA2, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.call(
        make_fake_TOA3, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.call(
        make_fake_TOA4, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    ptimes_nopickle = []
    ptimes_pickle = []
    ttimes = []
    t2times = []

    for tim in timfiles:
        print("Running PINT fitting w/o pickling...")
        # run PINT w/o pickling and average time over 5 runs
        pintrun("NGC6440E.par", tim, ptimes_nopickle, pickle=False, fitter="wls")

        print("Running PINT w/ pickling...")
        # run PINT with pickling and average time over 5 runs
        subprocess.call(
            "pintempo --usepickle NGC6440E.par " + tim,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )  # create pickle file
        pintrun("NGC6440E.par", tim, ptimes_pickle, pickle=True, fitter="wls")
        print("Running TEMPO...")
        temporun("NGC6440E.par", tim, ttimes, fitter="wls")
        print("Running Tempo2...")
        tempo2run("NGC6440E.par", tim, t2times)

    # create table 7 in PINT paper
    ntoas = [100, 1000, 10000, 100000]
    simple_comparison = Table(
        (ntoas, ttimes, t2times, ptimes_nopickle, ptimes_pickle),
        names=(
            "Number of TOAs",
            "TEMPO (sec)",
            "Tempo2 (sec)",
            "PINT - No Pickle (sec)",
            "PINT - Pickle (sec)",
        ),
    )
    ascii.write(
        simple_comparison,
        "simple_tables.pdf",
        Writer=ascii.Latex,
        latexdict={"tabletype": "table*"},
        overwrite=True,
    )

    # time the individual PINT functions
    importtimes = []
    getTOAs_nopickle = []
    getTOAs_pickle = []
    fittimes = []

    # setup
    m = models.get_model("NGC6440E.par")
    use_planets = False
    if m.PLANET_SHAPIRO.value:
        use_planets = True
    model_ephem = "DE421"
    if m.EPHEM is not None:
        model_ephem = m.EPHEM.value

    # time import statements in pintempo script
    print("timing imports...")
    total = 0
    for i in range(MAXIT):
        start = timeit.default_timer()
        import argparse
        import sys
        import astropy.units as u
        from astropy import log
        import pint.fitter
        import pint.models
        import pint.residuals

        end = timeit.default_timer()
        total = total + (end - start)
    importtimes.append(total / MAXIT)  # duplicate to match column size in table
    importtimes.append(total / MAXIT)
    importtimes.append(total / MAXIT)
    importtimes.append(total / MAXIT)

    for tim in timfiles:
        # no pickle time of get_TOAs
        print("timing get_TOAs w/o pickling...")
        total = 0
        for i in range(MAXIT):
            start = timeit.default_timer()
            toa.get_TOAs(tim, planets=use_planets, ephem=model_ephem, usepickle=False)
            end = timeit.default_timer()
            total = total + (end - start)
        getTOAs_nopickle.append(total / MAXIT)

        t = toa.get_TOAs(
            tim, planets=use_planets, ephem=model_ephem, usepickle=True
        )  # to use in timing fitter

        f = fitter.WLSFitter(t, m)

        print("timing fitter...")
        total = 0
        for i in range(MAXIT):
            start = timeit.default_timer()
            f.fit_toas()
            end = timeit.default_timer()
            total = total + (end - start)
        fittimes.append(total / MAXIT)

        # pickle time of get_TOAs
        print("timing get_TOAs w/ pickling...")
        total = 0
        for i in range(MAXIT):
            start = timeit.default_timer()
            toa.get_TOAs(tim, planets=use_planets, ephem=model_ephem, usepickle=True)
            end = timeit.default_timer()
            total = total + (end - start)
        getTOAs_pickle.append(total / MAXIT)

    # create table 8 in PINT paper
    ntoas = [100, 1000, 10000, 100000]
    function_comparison = Table(
        (ntoas, importtimes, getTOAs_nopickle, getTOAs_pickle, fittimes),
        names=(
            "Number of TOAs",
            "Import Statements (sec)",
            "Load TOAs - No Pickle (sec)",
            "Load TOAs - Pickle (sec)",
            "WLS Fitting - No Pickle (sec)",
        ),
    )
    ascii.write(
        function_comparison,
        "function_tables.pdf",
        Writer=ascii.Latex,
        latexdict={"tabletype": "table*"},
        overwrite=True,
    )

    # explore more complex model
    # use J1910+1256 with the following parameter additions to the par file (to ensure GLS fit with Tempo2):
    # - TNRedAmp -14.227505410948254
    # - TNRedGam 4.91353
    # - TNRedC 45

    # add needed params for GLS fitting
    subprocess.call(
        'echo "TNRedAmp -14.227505410948254" >> J1910+1256_NANOGrav_12yv4.tim',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.call(
        'echo "TNRedGam 4.91353" >> J1910+1256_NANOGrav_12yv4.tim',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.call(
        'echo "TNRedC 45" >> J1910+1256_NANOGrav_12yv4.tim',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # copy TOAs to create 2x the number of TOAs
    subprocess.call(
        "cat J1910+1256_NANOGrav_12yv4.tim > J1910+1256_NANOGrav_12yv4_10k.tim",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.call(
        "sed -n '6,6761p' J1910+1256_NANOGrav_12yv4.tim >> J1910+1256_NANOGrav_12yv4_10k.tim",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # copy TOAs to create 5x the number of TOAs
    subprocess.call(
        "cat J1910+1256_NANOGrav_12yv4.tim > J1910+1256_NANOGrav_12yv4_25k.tim",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for i in range(4):
        subprocess.call(
            "sed -n '6,6761p' J1910+1256_NANOGrav_12yv4.tim >> J1910+1256_NANOGrav_12yv4_25k.tim",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    timfiles2 = [
        "J1910+1256_NANOGrav_12yv4.tim",
        "J1910+1256_NANOGrav_12yv4_10k.tim",
        "J1910+1256_NANOGrav_12yv4_25k.tim",
    ]
    ptimes_nopickle2 = []
    ptimes_pickle2 = []
    ttimes2 = []
    t2times2 = []

    for tim in timfiles2:
        # run PINT w/o pickling and average time over 5 runs
        print("Running PINT w/o pickling...")
        pintrun(
            "J1910+1256_NANOGrav_12yv4.gls.par",
            tim,
            ptimes_nopickle2,
            pickle=False,
            fitter="gls",
        )

        # run PINT with pickling and average time over 5 runs
        print("Running PINT w/ pickling...")
        subprocess.call(
            "pintempo --usepickle J1910+1256_NANOGrav_12yv4.gls.par " + tim,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )  # create pickle file
        pintrun(
            "J1910+1256_NANOGrav_12yv4.gls.par",
            tim,
            ptimes_pickle2,
            pickle=True,
            fitter="gls",
        )

        print("running TEMPO...")
        temporun("J1910+1256_NANOGrav_12yv4.gls.par", tim, ttimes2, fitter="gls")

        print("running Tempo2...")
        tempo2run("J1910+1256_NANOGrav_12yv4.gls.par", tim, t2times2)

    # create table 9 in PINT paper
    ntoas = [5012, 10024, 25060]

    complex_comparison = Table(
        (ntoas, ttimes2, t2times2, ptimes_nopickle2, ptimes_pickle2),
        names=(
            "Number of TOAs",
            "TEMPO (sec)",
            "Tempo2 (sec)",
            "PINT - No Pickle (sec)",
            "PINT - Pickle (sec)",
        ),
    )
    ascii.write(
        complex_comparison,
        "complex_tables.pdf",
        Writer=ascii.Latex,
        latexdict={"tabletype": "table*"},
        overwrite=True,
    )
