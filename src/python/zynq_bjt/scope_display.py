"""Snapshot conversion, software edge location and conservative measurements.

Display operations never change the ADC clock or grant measurement qualification.
"""
import math
import statistics


def spectrum(values, rate, window='hann', remove_dc=True):
    """单边幅度谱，单位为输入单位的RMS；窗函数按相干增益修正。"""
    import numpy as np
    samples = np.asarray(values, dtype=float)
    if samples.ndim != 1 or len(samples)<8 or not np.isfinite(samples).all():
        raise ValueError('FFT requires at least 8 finite samples')
    if not math.isfinite(rate) or rate<=0 or window not in ('hann', 'rectangular', 'flattop'):
        raise ValueError('Invalid FFT rate/window')
    mean = float(samples.mean())
    total_rms = float(np.sqrt(np.mean(samples*samples)))
    ac_rms = float(np.sqrt(np.mean((samples-mean)**2)))
    if remove_dc: samples = samples-mean
    n = len(samples)
    phase = 2*np.pi*np.arange(n)/n
    hann = .5-.5*np.cos(phase)
    flat = .21557895-.41663158*np.cos(phase)+.277263158*np.cos(2*phase)-.083578947*np.cos(3*phase)+.006947368*np.cos(4*phase)
    weights = {'hann':hann,'flattop':flat,'rectangular':np.ones(n)}[window]
    amplitudes = np.abs(np.fft.rfft(samples*weights))/weights.sum()
    # DC和偶数长度的Nyquist点不乘sqrt(2)。
    amplitudes[1:len(amplitudes)-(1 if n%2==0 else 0)] *= math.sqrt(2)
    frequencies = np.fft.rfftfreq(n, 1/rate)
    # Locate on Hann (flat-top has an intentionally broad peak), then evaluate
    # the selected window at that frequency instead of reading a scalloped bin.
    search = np.abs(np.fft.rfft((samples-samples.mean())*hann))
    k = int(np.argmax(search[1:]))+1
    offset = 0.0
    if 1<=k<len(search)-1 and min(search[k-1:k+2])>0:
        a,b,c = np.log(search[k-1:k+2])
        if a-2*b+c: offset = float(np.clip(.5*(a-c)/(a-2*b+c),-.5,.5))
    peak_frequency = (k+offset)*rate/n
    def amplitude_at(frequency):
        return float(abs(np.sum(samples*weights*np.exp(-1j*phase*frequency*n/rate)))/weights.sum()*math.sqrt(2))
    resolved = 6 <= peak_frequency/(rate/n) < n/2-6 and ac_rms>1e-14
    peak_rms = amplitude_at(peak_frequency) if resolved else None
    harmonics = []
    if resolved:
        for order in (1,2,3,4,5,7,9):
            f = order*peak_frequency
            if f >= rate/2-6*rate/n: break
            harmonics.append(dict(order=order,frequency_hz=f,rms=amplitude_at(f)))
    return dict(frequency_hz=frequencies, rms=amplitudes,
                db=20*np.log10(np.maximum(amplitudes,1e-15)),
                bin_hz=rate/n, nyquist_hz=rate/2, window=window, remove_dc=remove_dc,
                total_rms=total_rms, ac_rms=ac_rms, mean=mean,
                peak_frequency_hz=peak_frequency if resolved else None, peak_rms=peak_rms,
                harmonics=harmonics, resolved=resolved)


def finite(value):
    return value is not None and math.isfinite(value)


def edge_positions(values, level, rising=True, hysteresis=0):
    """Interpolated crossings, rearmed only after leaving the hysteresis band.

    Invalid samples break continuity; an edge is never inferred across a gap.
    """
    hits, armed = [], False
    sign = 1 if rising else -1
    threshold = sign * level
    for i in range(1, len(values)):
        if not finite(values[i-1]) or not finite(values[i]):
            armed = False
            continue
        a, b = sign*values[i-1], sign*values[i]
        if a < threshold-hysteresis:
            armed = True
        if armed and a < threshold <= b:
            hits.append(i-1+(threshold-a)/(b-a))
            armed = False
    return hits


def measure(values, rate, *, invalid=False, noise_floor=0):
    result = dict(min=None, max=None, mean=None, vpp=None, rms=None,
                  ac_rms=None, frequency=None, period=None)
    if invalid or not values or not all(finite(v) for v in values):
        return result
    lo, hi = min(values), max(values)
    mean = statistics.mean(values)
    result.update(min=lo, max=hi, mean=mean, vpp=hi-lo,
                  rms=math.sqrt(statistics.mean(v*v for v in values)),
                  ac_rms=math.sqrt(statistics.mean((v-mean)**2 for v in values)))
    if hi-lo > noise_floor:
        hits = edge_positions(values, (lo+hi)/2, hysteresis=(hi-lo)*.1)
        periods = [b-a for a, b in zip(hits, hits[1:])]
        # Two complete, consistent periods and >=4 samples/cycle. This is an
        # estimate, not a frequency counter; it cannot detect aliasing.
        if len(periods) >= 2:
            period = statistics.mean(periods)
            if period >= 4 and statistics.pstdev(periods) <= period*.1:
                result.update(frequency=rate/period, period=period/rate)
    return result


def nice_step(value):
    """Round up to the familiar 1-2-5 instrument scale sequence."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Scale must be finite and positive')
    base = 10**math.floor(math.log10(value))
    return next(n*base for n in (1, 2, 5, 10) if n*base >= value*(1-1e-12))


def sample_at(values, rate, time_s):
    index = time_s*rate
    if not 0 <= index <= len(values)-1:
        return None
    i = int(index)
    j = min(i+1, len(values)-1)
    if not finite(values[i]) or not finite(values[j]):
        return None
    return values[i]+(values[j]-values[i])*(index-i)


def reference_channels(frame, calibration):
    channels = []
    for channel, words in enumerate(frame['words']):
        profile = (calibration.rx1, calibration.rx2)[channel]
        current_nominal = profile.get('validation_status') == 'generator_nominal_validated'
        adc_rates = frame.get('adc_sample_rates_hz') or frame['sample_rates_hz']
        rate_matches = abs(adc_rates[channel]/profile['sample_rate_hz']-1) <= .02
        codes = [word & 65535 for word in words]
        volts = []
        for word, code in zip(words, codes):
            try:
                value = None if word >> 16 or (current_nominal and not rate_matches) else calibration.port_v(code, channel)
            except ValueError:
                value = None
            volts.append(value)
        valid = [v for v in volts if v is not None]
        # Do not report a plausible mean from just the unsaturated part of a frame.
        complete = bool(valid) and len(valid) == len(volts)
        within_calibration = complete and all(profile['valid_min_v'] <= v <= profile['valid_max_v'] for v in valid)
        channels.append(dict(codes=codes, reference_volts=volts,
            mean_v=sum(valid)/len(valid) if complete else None,
            min_v=min(valid) if complete else None,
            max_v=max(valid) if complete else None,
            vpp_v=max(valid)-min(valid) if complete else None,
            invalid_samples=len(volts)-len(valid), overrange=sum(bool(w >> 16) for w in words),
            calibration_id=profile['calibration_id'],
            profile_sample_rate_hz=profile['sample_rate_hz'],
            capture_sample_rate_hz=frame['sample_rates_hz'][channel],
            voltage_basis=('linear_extrapolation' if complete and not within_calibration else
                           'generator_nominal_dc_calibration' if current_nominal and rate_matches else
                           'profile_rate_mismatch' if current_nominal else 'archived_dc_profile_unverified'),
            nominal_dc_calibrated=current_nominal and rate_matches and within_calibration,
            voltage_qualified=False))
    return channels
