"""Fit/independently validate RX1 nominal references, then write a candidate."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics

def fit(record):
    assert record['complete'] and record['generator_output_off_confirmed']
    assert record['board_close']['cleanup_confirmed']
    points = [p for p in record['points'] if p['accepted']]
    train = [p for p in points if p['role']=='fit']
    validation = [p for p in points if p['role']=='validation']
    assert len(train)>=5 and len(validation)>=5
    for p in points:
        assert len(p['captures'])==4
        assert all(not c['overrange'] and c['std_code']<60 for c in p['captures'])
        assert all(49e6<c['sample_rate_hz']<51e6 for c in p['captures'])
    x = [p['reference_v_nominal'] for p in train]
    y = [p['mean_code'] for p in train]
    xm,ym=statistics.fmean(x),statistics.fmean(y)
    slope=sum((a-xm)*(b-ym) for a,b in zip(x,y))/sum((a-xm)**2 for a in x)
    zero=ym-slope*xm
    assert abs(slope)>100 and min(x)<0<max(x)
    zero_q16=round(zero*65536)
    slope_nv=round(1e9/slope)
    checks=[dict(label=p['label'],role=p['role'],reference_v_nominal=p['reference_v_nominal'],
                 mean_code=p['mean_code'], voltage_v_nominal=(p['mean_code']-zero_q16/65536)*slope_nv/1e9,
                 error_v=(p['mean_code']-zero_q16/65536)*slope_nv/1e9-p['reference_v_nominal']) for p in points]
    error=max(abs(p['error_v']) for p in checks if p['role']=='validation')
    assert error<.005, ('Independent nominal validation exceeds 5 mV',error)
    return dict(calibration_id='rx1_generator_nominal_'+datetime.now().strftime('%Y%m%d_%H%M%S'),
        channel='RX1 / ADC B',sample_rate_hz=50000000,mode='DC bipolar',
        valid_min_v=min(x),valid_max_v=max(x),zero_code_q16=zero_q16,slope_nv_per_code=slope_nv,
        zero_code=zero_q16/65536,volts_per_code=slope_nv/1e9,
        validation_status='generator_nominal_validated',reference_basis=record['reference_basis'],
        generator_idn=record['generator_idn'],generator_load_display='High-Z',
        absolute_voltage_accuracy_verified=False,scope_relative=False,negative_calibrated=True,
        ac_response_calibrated=False,hardware_revision=record['hardware_revision']['revision'],
        board_identity=record['initialized']['identity'],
        independent_validation=dict(status='pass',points=len(validation),max_abs_error_v=error,
                                    limit_v_vs_generator_nominal=.005),
        fit_points=len(train),checks=checks,
        rejected_points=[dict(label=p['label'],volts=p['reference_v_nominal'],reason=p['rejection'])
                         for p in record['points'] if not p['accepted']],
        limitations=['Generator setpoints are the reference; no independent absolute voltage measurement.',
                     'Valid only for the recorded modified hardware and 50 MSPS DC capture.',
                     'This does not calibrate RX2, external transistor circuitry, current sources or AC response.'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('collection',type=Path);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();profile=fit(json.loads(a.collection.read_text(encoding='utf-8')))
    profile['collection']=str(a.collection)
    profile['collection_sha256']=hashlib.sha256(a.collection.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:profile[k] for k in ('calibration_id','valid_min_v','valid_max_v','zero_code','slope_nv_per_code','independent_validation')}))

if __name__=='__main__':main()
