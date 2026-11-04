"""TX3 多点波形参考；实测节点、插值和外推分别标记。"""
import bisect
import math


def resolve(profile, shape, frequency, vpp):
    if shape not in ('sine','square','triangle'):
        raise ValueError('Unsupported calibrated waveform')
    if not all(math.isfinite(v) and v>0 for v in (frequency,vpp)):
        raise ValueError('Frequency and Vpp must be positive and finite')
    # A user-stopped calibration may contain isolated independently revisited
    # nodes. Use those only at exact requests; never mix new/old code tables
    # across an unmeasured interpolation cell.
    overrides=profile.get('exact_overrides')
    if overrides:
        matches=[r for r in overrides['points'] if r['shape']==shape
                 and math.isclose(r['frequency_hz'],frequency,rel_tol=1e-12)
                 and math.isclose(r['target_vpp_v'],vpp,rel_tol=1e-12)]
        if matches:
            return resolve(dict(profile,exact_overrides=None,points=matches,
                shape_validation=overrides['shape_validation']),shape,frequency,vpp)
    rows=[r for r in profile['points'] if r['shape']==shape]
    if not rows: raise ValueError('No verified TX3 waveform points')
    shape_validation=profile.get('shape_validation',{}).get(shape,{})
    def usable(row):
        return row['passed'] or (shape_validation.get('amplitude_only') is True and row.get('amplitude_passed') is True)
    frequencies=sorted({r['frequency_hz'] for r in rows})
    amplitudes=sorted({r['target_vpp_v'] for r in rows})
    def bracket(values, value):
        clamped=max(values[0],min(values[-1],value))
        right=min(bisect.bisect_left(values,clamped),len(values)-1)
        if values[right]==clamped:return [(clamped,1.)]
        left=right-1;fraction=(clamped-values[left])/(values[right]-values[left])
        return [(values[left],1-fraction),(values[right],fraction)]
    zero=peak=0.
    for f,fw in bracket(frequencies,frequency):
        for a,aw in bracket(amplitudes,vpp):
            match=[r for r in rows if r['frequency_hz']==f and r['target_vpp_v']==a]
            if len(match)!=1 or not usable(match[0]):
                raise ValueError('Requested TX3 region includes an unverified point')
            row=match[0]
            z,p=row['zero_code'],row['peak_codes']
            if not all(type(v) is int for v in (z,p)) or not 0<=z-p<z+p<=65535:
                raise ValueError('Invalid TX3 calibration code')
            zero+=z*fw*aw;peak+=p*fw*aw
    bounded_vpp=max(amplitudes[0],min(amplitudes[-1],vpp))
    peak*=vpp/bounded_vpp
    max_vpp=vpp*min(zero,65535-zero)/peak
    if not 0<=zero-peak<=zero+peak<=65535:
        raise ValueError('TX3 waveform exceeds DAC code range')
    exact=any(r['frequency_hz']==frequency and math.isclose(r['target_vpp_v'],vpp,rel_tol=1e-12) and usable(r) for r in rows)
    outside=not (frequencies[0]<=frequency<=frequencies[-1] and amplitudes[0]<=vpp<=amplitudes[-1])
    stable=shape_validation.get('amplitude_stability_qualified',True)
    return dict(zero_code=zero,peak_codes=peak,max_vpp=max_vpp,
                amplitude_basis=('scope_verified_grid' if stable else 'scope_checked_unstable_reference') if exact else ('extrapolated_grid_unverified' if outside else 'interpolated_grid_unverified'),
                amplitude_stability_qualified=stable,
                reference_vpp=.07,scale=vpp/.07,warm_reference=None,offset_validation_status=shape_validation.get('offset_validation_status',profile.get('offset_validation_status','session_only')),
                dac_sample_rate_hz=profile['dac_sample_rate_hz'],calibration_id=profile['calibration_id'])
