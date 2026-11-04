"""Publish only independently verified, cleaned-up scope measurements to data/."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[3]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tx2',type=Path,required=True);ap.add_argument('--tx3',type=Path,required=True)
    args=ap.parse_args()
    results=[json.loads(p.read_text()) for p in (args.tx2,args.tx3)]
    for r in results:
        assert r['status']=='completed' and r['verified'] and r['close']['cleanup_confirmed']
        assert r['initialized']['identity']['dac_divider']==20
    dc,sine=results
    assert len(dc['candidate_codes'])==181 and len(dc['verification'])==73
    assert len(sine['frequency_hz'])==len(sine['candidate_peaks'])==len(sine['verification'])==78
    assert len(sine['midpoints'])==12
    if sine.get('amplitude_calibration_source'):
        assert len(sine['final_zero_verification'])==13
    path=ROOT/'data/dac_calibration.json'
    old=path.read_bytes();d=json.loads(old)
    prior=ROOT/'report/tx23_calibration_20261030/prior/dac_calibration.json'
    assert prior.read_bytes()==old,'Active data changed since the saved baseline'
    d.update(version='tx2-dc-tx3-sine-custom50-20261030',calibration_id='26103050',
             source=[str(args.tx2),str(args.tx3)],previous_sha256=hashlib.sha256(old).hexdigest(),
             conditions='Current repaired ADDA carrier, PYNQ custom50, ADC/DAC 50 MSPS, AD9747 FSC 0x01F9. TX2 -> Rigol DS1104Z DS1ZA173719283 CH3; TX3 -> CH4; direct coax, high impedance, DC, x1, non-inverted. Scope-relative, not traceable DMM calibration.',
             limitations='TX2: 37 measured/corrected 50 mV knots over 0..1.8 V, represented by 181 interpolated 10 mV entries; independent reverse checks at 73 knots/midpoints. TX3: 78 frequency knots and 12 midpoints over 10 kHz..6 MHz, verified at 50 mVpp and zero offset; amplitude means fitted sine fundamental, not noisy extrema. Smaller amplitudes are scaled estimates; other loads, waveforms, offsets, sample rates and cold-start/temperature conditions are unqualified. RX calibration remains historical and requires remeasurement after circuit modifications. TX1 remains nominal.')
    p=d['channels'][1]
    slope=float(np.polyfit([x['code'] for x in dc['points']],[x['measurement']['mean_v'] for x in dc['points']],1)[0])
    p.update(zero_code=dc['candidate_codes'][0],reference_uv=round(slope*16384*1e6),reference_codes=16384,
             min_uv=0,max_uv=1800000,validated_min_uv=0,validated_max_uv=1800000,
             dc_calibrated=True,estimated=False,scope_relative=True,dac_sample_rate_hz=50000000,
             verification_source=str(args.tx2),verified_max_dc_error_uv=dc['max_verification_error_v']*1e6)
    p['dc_table']=dict(step_uv=10000,codes=dc['candidate_codes'],measured_knot_step_uv=50000,
                       measured_knot_codes=dc['candidate_knot_codes'],source=str(args.tx2),
                       validation_status='verified_custom50_37_knots_36_midpoints',
                       validation_points=73,scope_relative=True)
    old_sine=d['channels'][2]['sine_50mv']
    profile=dict(frequency_hz=sine['frequency_hz'],peak_codes=sine['candidate_peaks'],zero_code=sine['zero_code'],
                 target_vpp_uv=50000,target_offset_uv=0,dac_sample_rate_hz=50000000,
                 zero_local_slope_v_per_code=sine['zero_slope_v_per_code'],scope_relative=True,
                 conditions='TX3 -> Rigol DS1104Z DS1ZA173719283 CH4, high impedance coax, DC x1, 10 mV/div, 50 MSPS DAC, full bandwidth. Fresh RUN/STOP, 12000 RAW samples, fundamental fit and 1200-point screen amplitude cross-check.',
                 validation_status='verified_custom50_scope_78_points_midpoints',source=str(args.tx3),
                 verification_source=str(args.tx3),verified_max_vpp_error_uv=sine['max_vpp_error_v']*1e6,
                 verified_max_dc_error_uv=sine['max_dc_error_v']*1e6,
                 prior_profile_source=old_sine.get('source'),prior_zero_code=old_sine['zero_code'])
    if sine.get('amplitude_calibration_source'):
        profile.update(amplitude_calibration_source=sine['amplitude_calibration_source'],
                       amplitude_verification_zero_code=sine['amplitude_verification_zero_code'],
                       final_zero_verification_points=13,
                       zero_refinement_conditions='After thermal settling and amplitude sweep; final zero checked at 13 frequency visits, including return to 100 kHz. Prior 78-knot/12-midpoint amplitude evidence retains its original integer zero code.')
    d['channels'][2]['sine_50mv']=profile
    d['channels'][2]['zero_code']=sine['zero_code']
    d['channels'][2]['reference_uv']=round(sine['zero_slope_v_per_code']*16384*1e6)
    d['calibrated_at']=datetime.now(timezone(timedelta(hours=8))).isoformat()
    path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         tx2_zero_code=p['zero_code'],tx3_zero_code=profile['zero_code'])))


if __name__=='__main__':main()
