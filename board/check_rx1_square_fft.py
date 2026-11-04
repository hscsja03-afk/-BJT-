"""Capture CH1 -> RX1. Optional bounded frequency/duty sweep restores settings."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from tx2_scope_zero import SerialAgent,ROOT
from calibrate_rx1_generator import Generator
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration
from zynq_bjt.scope_display import reference_channels,spectrum


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--count',type=int,default=1024)
    ap.add_argument('--bitfile');ap.add_argument('--label',default='baseline');ap.add_argument('--sweep',action='store_true')
    args=ap.parse_args();out=ROOT/'report/datasheet_fft_acquisition_20261102'/args.label;out.mkdir(parents=True,exist_ok=True)
    result=dict(connection='DG1032Z CH1 -> RX1 (user confirmed)',events=[],captures=[],cleanup_confirmed=False)
    agent=SerialAgent('COM7',os.environ.get('PYNQ_SSH_PASSWORD','xilinx'),result['events'],
                      base=ROOT/'build/work/adc_fft_agent_20261102',bitfile=args.bitfile)
    generator=None;initial=None;changed=False
    class SlowGenerator(Generator):
        def call(self,kind,command):
            time.sleep(max(0,.35-(time.monotonic()-self.last)))
            return super().call(kind,command)
    try:
        generator=SlowGenerator(out/'generator.jsonl')
        result['generator']={q:generator.ask(q) for q in (':SOUR1:FUNC?',':SOUR1:FREQ?',':SOUR1:VOLT?',':SOUR1:VOLT:OFFS?',':SOUR1:FUNC:SQU:DCYC?',':OUTP1?',':OUTP1:LOAD?')}
        initial=result['generator']
        if args.sweep:
            assert initial[':SOUR1:FUNC?']=='SQU' and abs(float(initial[':SOUR1:VOLT:OFFS?']))<1e-9
            assert .01<=float(initial[':SOUR1:VOLT?'])<=1.0 and float(initial[':OUTP1:LOAD?'])>1e6
            assert generator.ask(':SOUR1:TRACK?')=='OFF'
        result['connected']=agent.connect();result['initialized']=agent.call('initialize',timeout=120)
        cal=Calibration(ROOT/'data')
        plans=[(64,f,duty) for f in (2300,8000,23700) for duty in (50,30)] if args.sweep else [(stride,None,None) for stride in (16,64,128)]
        for stride,frequency,duty in plans:
            if frequency is not None:
                changed=True
                generator.write(':SOUR1:FREQ '+str(frequency));generator.write(':SOUR1:FUNC:SQU:DCYC '+str(duty))
                assert abs(float(generator.ask(':SOUR1:FREQ?'))-frequency)<.01
                assert abs(float(generator.ask(':SOUR1:FUNC:SQU:DCYC?'))-duty)<.01
                time.sleep(1)
            for repeat in range(2):
                frame=agent.call('capture',dict(sample_count=args.count,sample_stride=stride),timeout=30)
                name='frame_{}_{}_{}_{}.json'.format(frequency,duty,stride,repeat)
                (out/name).write_text(json.dumps(frame),encoding='utf-8')
                assert not frame['simulated'] and len(frame['words'][0])==args.count
                volts=reference_channels(frame,cal)[0]['reference_volts']
                fft=spectrum(volts,frame['sample_rates_hz'][0],'flattop')
                result['captures'].append(dict(file=name,frequency_set_hz=frequency,duty_percent=duty,rate_hz=frame['sample_rates_hz'][0],stride=stride,count=args.count,
                    vpp=max(volts)-min(volts),**{k:fft[k] for k in ('peak_frequency_hz','peak_rms','ac_rms','harmonics','resolved','bin_hz')}))
                time.sleep(.4)
    except BaseException as error:result['error']=repr(error);raise
    finally:
        try:result['closed']=agent.close();result['cleanup_confirmed']=True
        finally:
            try:
                if generator and changed:
                    generator.write(':SOUR1:FREQ '+initial[':SOUR1:FREQ?'])
                    generator.write(':SOUR1:FUNC:SQU:DCYC '+initial[':SOUR1:FUNC:SQU:DCYC?'])
                    result['restored']={q:generator.ask(q) for q in initial}
                    assert result['restored']==initial
            finally:
                if generator:generator.s.close()
                (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k in ('captures','cleanup_confirmed')},ensure_ascii=False))


if __name__=='__main__':main()
