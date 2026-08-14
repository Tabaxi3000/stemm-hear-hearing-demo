"""firwin2 + MATLAB-derived fir2, vendored from The PyClarity Team (MIT),
clarity/evaluator/msbg/msbg_utils.py -- used by the vendored NAL-R for HASQI/HAAQI."""
from __future__ import annotations
import math
import numpy as np
from numpy import ndarray
from scipy.signal.windows import hamming, kaiser


def firwin2(
    n_taps: int,
    frequencies: list[float] | ndarray,
    filter_gains: list[float] | ndarray,
    window: tuple[str, int] | str | None = None,
    antisymmetric: bool | None = None,  # pylint: disable=W0613
) -> ndarray:  # pylint: disable=W0613
    """FIR filter design using the window method.

    Partial implementation of scipy firwin2 but using our own MATLAB-derived fir2.

    Args:
        n_taps (int): The number of taps in the FIR filter.
        frequencies (ndarray): The frequency sampling points. 0.0 to 1.0 with 1.0
            being Nyquist.
        filter_gains (ndarray): The filter gains at the frequency sampling points.
        window (string or (string, float), optional): See scipy.firwin2. Default is None
        antisymmetric (bool, optional): Unused but present to maintain compatibility
            with scipy firwin2.

    Returns:
        ndarray:  The filter coefficients of the FIR filter, as a 1-D array of length n.

    """
    window_shape = None
    window_type = None
    if isinstance(window, tuple):
        window_type, window_param = window if window is not None else (None, 0)
    else:
        window_type, window_param = window, None

    order = n_taps - 1

    if window_type == "kaiser":
        window_shape = kaiser(n_taps, window_param)

    if window_shape is None:
        filter_coef, _ = fir2(order, frequencies, filter_gains)
    else:
        filter_coef, _ = fir2(order, frequencies, filter_gains, window_shape)

    return filter_coef


def fir2(
    filter_length: int,
    frequencies: list[float] | ndarray,
    filter_gains: list[float] | ndarray,
    window_shape: ndarray | None = None,
) -> tuple[ndarray, int]:
    """FIR arbitrary shape filter design using the frequency sampling method.

    Partial implementation of MATLAB fir2.

    Args:
        filter_length (int): Order
        frequencies (ndarray): The frequency sampling points (0 < frequencies < 1) where
            1 is Nyquist rate. First and last elements must be 0 and 1 respectively.
        filter_gains (ndarray): The filter gains at the frequency sampling points.
        window_shape (ndarray, optional): window to apply.
            (default: hamming window)

    Returns:
        np.ndarray: nn + 1 filter coefficients, 1

    """
    # Work with filter length instead of filter order
    filter_length += 1

    if window_shape is None:
        window_shape = hamming(filter_length)

    n_interpolate = (
        2 ** np.ceil(math.log(filter_length) / math.log(2.0))
        if filter_length >= 1024
        else 512
    )

    lap = np.fix(n_interpolate / 25).astype(int)

    nbrk = max(len(frequencies), len(filter_gains))

    frequencies[0] = 0
    frequencies[nbrk - 1] = 1

    H = np.zeros(n_interpolate + 1)
    nint = nbrk - 1
    df = np.diff(frequencies, n=1)

    n_interpolate += 1
    nb = 0
    H[0] = filter_gains[0]

    for i in np.arange(nint):
        if df[i] == 0:
            nb = int(np.ceil(nb - lap / 2))
            ne: int = nb + lap - 1
        else:
            ne = int(np.fix(frequencies[i + 1] * n_interpolate)) - 1

        j = np.arange(nb, ne + 1)
        inc: float | np.ndarray = 0.0 if nb == ne else (j - nb) / (ne - nb)
        H[nb : (ne + 1)] = inc * filter_gains[i + 1] + (1 - inc) * filter_gains[i]
        nb = ne + 1

    dt = 0.5 * (filter_length - 1)
    rad = -dt * 1j * math.pi * np.arange(0, n_interpolate) / (n_interpolate - 1)
    H = H * np.exp(rad)

    H = np.concatenate((H, H[n_interpolate - 2 : 0 : -1].conj()))
    ht = np.real(np.fft.ifft(H))

    b = ht[0:filter_length] * window_shape

    return b, 1
