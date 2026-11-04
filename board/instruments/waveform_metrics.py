"""Full-bandwidth square-wave plateau statistics, independent of DAC targets."""
import numpy as np


def square_plateaus(values, sample_period_s, frequency_hz):
    values = np.asarray(values, dtype=float)
    phase = 2*np.pi*frequency_hz*np.arange(len(values))*sample_period_s
    design = np.column_stack((np.ones(len(values)), np.sin(phase), np.cos(phase)))
    fit = np.linalg.lstsq(design, values, rcond=None)[0]
    phase += np.arctan2(fit[2], fit[1])
    carrier = np.sin(phase)
    # Use only the central half of each plateau. Edges/ringing remain in the
    # raw trace but do not define the plateau level. Means avoid a one-ADC-code
    # jump when a quantized level's median crosses its 50-percent boundary.
    high = values[carrier > 2**-.5]
    low = values[carrier < -2**-.5]
    if min(len(high), len(low)) < max(100, len(values)//10):
        raise ValueError('Insufficient square plateau coverage')
    hi, lo = float(high.mean()), float(low.mean())
    if hi <= lo:
        raise ValueError('Nonpositive square plateau span')
    return dict(vpp_v=hi-lo, dc_v=(hi+lo)/2,
                high_mean_v=hi, low_mean_v=lo,
                high_std_v=float(high.std()), low_std_v=float(low.std()),
                high_count=len(high), low_count=len(low),
                quantile_vpp_v=float(np.quantile(values,.75)-np.quantile(values,.25)))
