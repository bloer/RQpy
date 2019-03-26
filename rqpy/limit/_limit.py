import numpy as np
from glob import glob
import time
import os
from scipy import stats, signal, interpolate, constants, special

import rqpy as rp
import mendeleev


__all__ = ["optimuminterval",
           "gauss_smear",
           "drde",
           "helmfactor",
          ]


def helmfactor(er, tm='Si'):
    """
    The analytic nuclear form factor via the Helm approximation.

    Parameters
    ----------
    er : array_like
        The recoil energy to use in the form factor calculation, units of keV.
    tm : str, int, optional
        The target material of the detector. Can be passed as either the atomic symbol, the
        atomic number, or the full name of the element. Default is 'Si'.

    Returns
    -------
    ffactor2 : ndarray
        The square of the dimensionless form factor for the inputted recoil energies and target
        material.

    Notes
    -----
    This form factor uses Helm's approximation to the charge density of the nucleus, as explained by
    Lewin and Smith in section 4 of their paper:
        - https://doi.org/10.1016/S0927-6505(96)00047-3

    """

    er = np.atleast_1d(er)

    hbarc = constants.hbar * constants.c / constants.e * 1e-6 * 1e15 # [MeV fm]
    mn = constants.atomic_mass * constants.c**2 / constants.e * 1e-9 # 1 amu in [GeV]
    atomic_weight = mendeleev.element(tm).atomic_weight

    # dimensionless momentum transfer
    q = np.sqrt(2 * mn * atomic_weight * er) # [MeV]

    # using the parameters defined in L&S
    s = 0.9 # [fm]
    a = 0.52 # [fm]
    c = 1.23 * atomic_weight**(1 / 3) - 0.60 # [fm]

    # approximation of rn [Eq. 4.11 of L&S]
    rn = np.sqrt(c**2 + 7 / 3 * np.pi**2 * a**2 - 5 * s**2)

    qrn = q * rn / hbarc
    qs = q * s / hbarc

    # Helm approximation of form facter [Eq. 4.7 of L&S]
    ffactor2 = (3 * special.spherical_jn(1, qrn) / qrn * np.exp(-qs**2 / 2))**2 

    return ffactor2


def drde(q, m_dm, sig0, tm='Si'):
    """
    The differential scattering rate of an expected WIMP.

    Parameters
    ----------
    q : array_like
        The recoil energies at which to calculate the dark matter differential
        scattering rate. Expected units are keV.
    m_dm : float
        The dark matter mass at which to calculate the expected differential
        scattering rate. Expected units are GeV.
    sig0 : float
        The dark matter cross section at which to calculated the expected differential
        scattering rate. Expected units are cm^2.
    tm : str, int, optional
        The target material of the detector. Can be passed as either the atomic symbol, the
        atomic number, or the full name of the element. Default is 'Si'.

    Returns
    -------
    rate : ndarray
        The expected dark matter differential scattering cross section for the inputted recoil
        energies, dark matter mass, and dark matter cross section. Units are events/keV/kg/day, 
        or "DRU".

    Notes
    -----
    The derivation of the expected dark matter differential scattering rate is done in Lewin and
    Smith's paper "Review of mathematics, numerical factors, and corrections dark matter experiments
    based on elastic nuclear recoil", which can be found here:
        - https://doi.org/10.1016/S0927-6505(96)00047-3

    The derivation by L&S is incomplete, see Eq. 22 of R. Schnee's paper "Introduction to Dark Matter
    Experiments", which includes the correct rate for `vmin` in the range (`vesc` - `ve`, `vesc` + `ve`)
        - https://arxiv.org/abs/1101.5205

    Another citation for this correction can be found in Savage, et. al.'s paper "Compatibility of
    DAMA/LIBRA dark matter detection with other searches", see Eq. 19. This is a different parameterization,
    but is the same solution.
        - https://doi.org/10.1088/1475-7516/2009/04/010

    """

    q = np.atleast_1d(q) # convert to recoil energy in keV

    v0 = 220e3 # sun velocity about glactic center [m/s]
    ve = 232e3 # mean orbital velocity of Earch [m/s]
    vesc = 544e3 # galactic escape velocity [m/s]
    rho0 = 0.3 # local DM density [GeV/cm^3]

    a = mendeleev.element(tm).atomic_weight
    mn = constants.atomic_mass * constants.c**2 / constants.e * 1e-9 # nucleon mass (1 amu) [GeV]
    mtarget = a * mn # nucleon mass for tm [GeV]
    r = 4 * m_dm * mtarget / (m_dm + mtarget)**2 # unitless reduced mass parameter
    e0 = 0.5 * m_dm * (v0 / constants.c)**2 * 1e6 # kinetic energy of dark matter [keV]
    vmin = np.sqrt(q / (e0 * r)) * v0 # DM velocity for smallest particle energy to give recoil energy q

    form_factor = helmfactor(q, tm=tm)

    # spin-independent cross section on entire nucleus
    sigma = form_factor * sig0 * a**2 * (mtarget/(m_dm + mtarget))**2 / (mn / (m_dm + mn))**2

    # event rate per unit mass for ve= 0 and vesc = infinity [Eq. 3.1 of L&S]
    r0con = 2 * constants.N_A / np.sqrt(np.pi) * 1e5 * constants.day
    r0 = r0con * sigma * rho0 * v0 / (a * m_dm)

    # ratio of k0/k1 [Eq. 2.2 of L&S]
    k0_over_k1 = 1 / (special.erf(vesc / v0) - 2 / np.sqrt(np.pi) * vesc / v0 * np.exp(-(vesc / v0)**2))

    # rate integrated to infinity [Eq. 3.12 of L&S]
    rate_inf = r0 * np.sqrt(np.pi) * v0 / (4 * e0 * r * ve) * (special.erf((vmin + ve) / v0) - special.erf((vmin - ve) / v0))
    # rate integrated to vesc [Eq. 3.13 of L&S]
    rate_vesc = k0_over_k1 * (rate_inf - r0 / (e0 * r) * np.exp(-(vesc / v0)**2))

    # rate calculation correction to L&S for `vmin` in range (`vesc` - `ve`, `vesc` + `ve`) [Eq. 22 of Schnee]
    rate_inf2 = r0 * np.sqrt(np.pi) * v0 / (4 * e0 * r * ve) * (special.erf(vesc / v0) - special.erf((vmin - ve) / v0))
    rate_high_vmin = k0_over_k1 * (rate_inf2 - r0 / (e0 * r) * (vesc + ve - vmin) / (2 * ve) * np.exp(-(vesc / v0)**2))

    # combine the calculations based on their regions of validity
    rate = np.zeros(q.shape)
    rate[(vmin < vesc - ve) & (vmin > 0)] = rate_vesc[(vmin < vesc - ve) & (vmin > 0)]
    rate[(vmin > vesc - ve) & (vmin < vesc + ve)] = rate_high_vmin[(vmin > vesc - ve) & (vmin < vesc + ve)]

    return rate


def gauss_smear(x, f, res, nres=1e5, gauss_width=10):
    """
    Function for smearing an array of values by a gaussian.

    Parameters
    ----------
    x : array_like
        The x-values of the array `f` that will be smeared.
    f : array_like
        The array of value to smear via a Gaussian distribution.
    res : float
        The width of the gaussian (1 standard deviation) that will be
        used to smear the inputted array. Should have the same units as `x`.
    nres : float, optional
        The size of the array that the Gaussian distribution will be saved to.
        Default is 1e5.
    gauss_width : float, optional
        The number of standard deviations of the Gaussian distribution that the
        smearing will go out to. Default is 10.

    Returns
    -------
    sx : ndarray
        The inputted array `f` after being smeared by the Gaussian distribution.

    """

    x2 = np.linspace(min(x), max(x), num=int(nres))
    spacing = np.mean(np.diff(x2))
    f2 = interpolate.interp1d(x, f)

    xgauss = np.arange(-gauss_width*res, gauss_width*res, spacing)
    gauss = stats.norm.pdf(xgauss, scale=res)

    sce = signal.convolve(f2(x2), gauss, mode="full") * spacing
    e_conv = np.arange(-gauss_width*res, gauss_width*res + x2[-1]-x2[0], spacing)
    s = interpolate.interp1d(e_conv, sce)

    return s(x)


def _get_fileid(oi_path):
    """
    Helper function for determining an unused or old file number when running the Optimum Interval code.
    
    Parameters
    ----------
    oi_path : str
        The path to the compiled Fortran code for the Optimum Interval algorithm.

    Returns
    -------
    fileid : int
        A number from 0 to 99 to use as the number to append to ULinput/ULoutput. Allows running of OI
        code in parallel. This chooses a file ID that corresponds to the oldest ULoutput file.

    """

    filelist = glob(f"{oi_path}ULoutput[0-9]")
    filelist.extend(glob(f"{oi_path}ULoutput[0-9][0-9]"))

    mtimes = []
    fileids = []

    for f in filelist:
        mtimes.append(os.path.getmtime(f))
        fileids.append(int(f.split('ULoutput')[-1]))

    if len(filelist) == 0:
        fileid = 0
    elif len(mtimes) == 100:
        fileid = fileids[np.argmin(mtimes)]
    else:
        fileid = np.random.choice([ii for ii in range(100) if ii not in fileids])

    return fileid


def optimuminterval(eventenergies, effenergies, effs, masslist, exposure,
                    tm="Si", res=None, verbose=False, oi_path=None):
    """
    Function for running Steve Yellin's Optimum Interval code on an inputted spectrum and efficiency curve.

    Parameters
    ----------
    eventenergies : ndarray
        Array of all of the event energies (in keV) to use for calculating the sensitivity.
    effenergies : ndarray 
        Array of the energy values (in keV) of the efficiency curve.
    effs : ndarray
        Array of the efficiencies (unitless) corresponding to `effenergies`.
    masslist : ndarray
        List of candidate DM masses (in GeV/c^2) to calculate sensitivity at.
    exposure : float
        The total exposure of the detector (kg*days).
    tm : str, int, optional
        The target material of the detector. Can be passed as either the atomic symbol, the
        atomic number, or the full name of the element. Default is 'Si'.
    res : float, optional
        The detector resolution in units of keV. If passed, then the differential scattering
        rate of the dark matter is convoluted by a gaussian with width `res`, which results
        in a smeared spectrum. If left as None, no smearing is performed.
    verbose : bool, optional
        If True, then the algorithm prints out the number of mass that it is currently calculating
        the limit for. If False, no information is printed. Default is False.
    oi_path : str, optional
        The path to the compiled Fortran code for the Optimum Interval. Since this function is a wrapper
        for the `CalcOptLim3_VarNm` Fortran program, the path to that compiled program must be passed. If
        this is left as None, an error will be raised.

    Returns
    -------
    m : ndarray
        The masses (in GeV/c^2) at which the sensitvity curve was calculated.
    sig : ndarray
        The corresponding cross sections of the sensitivity curve (in cm^2).
    interval_low : ndarray
        The lower energy bound of the interval found via the Optimum Interval algorithm (in keV).
    interval_high : ndarray
        The uppper energy bound of the interval found via the Optimum Interval algorithm (in keV).

    Raises
    ------
    ValueError
        If `oi_path` was left as None
        If `os.name` is not 'posix'

    Notes
    -----
    This function is a wrapper for Steve Yellin's Optimum Interval code. His code can be found
    here: titus.stanford.edu/Upperlimit/

    Read more about the Optimum Interval code in these two papers:
        - https://arxiv.org/abs/physics/0203002
        - https://arxiv.org/abs/0709.2701

    """

    if oi_path is None:
        raise ValueError("Please specify oi_path to point to the directory of CalcOptLim3_VarNm.")

    if np.isscalar(masslist):
        masslist = [masslist]

    elow = max(0.001, min(effenergies))
    ehigh = max(effenergies)

    en_interp = np.logspace(np.log10(0.9*elow), np.log10(1.1*ehigh), 1e5)

    delta_e = np.concatenate(([(en_interp[1] - en_interp[0])/2],
                              (en_interp[2:] - en_interp[:-2])/2,
                              [(en_interp[-1] - en_interp[-2])/2]))

    sigma0 = 1e-41

    event_inds = rp.inrange(eventenergies, elow, ehigh)
    inlim = rp.inrange(en_interp, elow, ehigh)

    exp = effs * exposure

    curr_exp = interpolate.interp1d(effenergies, exp,
                                    kind="linear",
                                    bounds_error=False,
                                    fill_value=(0, exp[-1]))

    sigsi = np.zeros(len(masslist))
    mass_out = np.zeros(len(masslist))
    interval_low = np.zeros(len(masslist))
    interval_high = np.zeros(len(masslist))

    fileid = _get_fileid(oi_path)

    for ii, mass in enumerate(masslist):
        if verbose:
            print(f"On mass {ii+1} of {len(masslist)}.")

        init_rate = drde(en_interp, mass, sigma0, tm=tm)

        if res is not None:
            init_rate = gauss_smear(en_interp, init_rate, res)

        rate = init_rate * curr_exp(en_interp)

        integ_rate = np.cumsum(rate * delta_e * inlim)

        integ_rate[0] = 0
        tot_rate = integ_rate[-1]

        x_val_fcn = interpolate.interp1d(en_interp, integ_rate,
                                         kind="linear",
                                         bounds_error=True)

        x_vals = x_val_fcn(eventenergies[event_inds])

        fc = x_vals/tot_rate
        fc[fc > 1] = 1

        cdf_max = 1 - 1e-6
        possiblewimp = fc <= cdf_max
        nwimps = possiblewimp.sum()
        fc = fc[possiblewimp]
        totengs = eventenergies[event_inds][possiblewimp]

        ulinput_arr = np.zeros(3 + len(fc))
        ulinput_arr[0] = 1
        ulinput_arr[1] = mass
        ulinput_arr[2] = tot_rate

        if len(ulinput_arr) > 3:
            ulinput_arr[3:] = fc

        np.savetxt(f"{oi_path}ULinput{fileid}", ulinput_arr[np.newaxis,:], newline='',
                   fmt='%10.6e\n' + '%10.6f\n' + '%10.6e\n' * len(fc) + '%10.6e')

        if os.name == 'posix':
            if os.path.exists(f"{oi_path}ULoutput{fileid}"):
                os.remove(f"{oi_path}ULoutput{fileid}")
            os.system(f"(cd {oi_path} && ./CalcOptLim3_VarNm ULinput{fileid} ULoutput{fileid})")
        else:
            raise ValueError("Only Linux is currently supported by optimuminterval.")

        uloutput = np.loadtxt(f"{oi_path}ULoutput{fileid}")

        sigsi[ii] = uloutput[0] * sigma0
        mass_out[ii] = uloutput[1]
        if len(totengs)>0:
            interval_low[ii] = totengs[int(uloutput[3])]
            if int(uloutput[4]) < nwimps:
                interval_high[ii] = totengs[int(uloutput[4])]
            else:
                interval_high[ii] = totengs[-1]

    return mass_out, sigsi, interval_low, interval_high
