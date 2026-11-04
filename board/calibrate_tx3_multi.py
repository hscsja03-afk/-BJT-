"""TX3→CH3：低频率仪表命令、多波形多幅度修正与倒序复测。"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import time
import numpy as np
from calibrate_tx23_scope import Scope, fit_sine
from tx2_scope_zero import SerialAgent, ROOT
from waveform_metrics import square_plateaus


class SlowScope(Scope):
    def call(self, method, value):
        time.sleep(max(0, .35-(time.monotonic()-self.last)))
        try: return getattr(self.s, method)(value)
        finally: self.last = time.monotonic()

    def sample(self, path, frequency, shape):
        self.write(':RUN'); time.sleep(1.5); self.write(':STOP')
        if self.ask(':TRIGger:STATus?') != 'STOP': raise RuntimeError('Scope did not stop')
        self.write(':WAVeform:MODE RAW')
        self.write(':WAVeform:STARt 1'); self.write(':WAVeform:STOP 12000')
        pre = [float(v) for v in self.ask(':WAVeform:PREamble?').split(',')]
        block = self.ask_raw(b':WAVeform:DATA?')
        if block[:1] != b'#': raise RuntimeError('Invalid waveform block')
        nd = int(block[1:2]); count = int(block[2:2+nd])
        raw = np.frombuffer(block[2+nd:2+nd+count], dtype=np.uint8).copy()
        rate = float(self.ask(':ACQuire:SRATe?'))
        np.savez_compressed(path, raw=raw, preamble=pre, sample_rate_hz=rate)
        if len(raw)!=12000 or int(pre[2])!=12000 or abs(pre[4]*rate-1)>1e-5:
            raise RuntimeError('Stale or incomplete acquisition')
        if not self.scale*.005 < pre[7] < self.scale*.2:
            raise ValueError('Invalid scope RAW vertical metadata: '+str(pre[7]))
        fit = fit_sine(raw, pre, frequency)
        self.write(':WAVeform:MODE NORM');self.write(':WAVeform:STARt 1');self.write(':WAVeform:STOP 1200')
        screen_pre=[float(v) for v in self.ask(':WAVeform:PREamble?').split(',')]
        screen_block=self.ask_raw(b':WAVeform:DATA?')
        if screen_block[:1]!=b'#':raise ValueError('Invalid screen waveform block')
        digits=int(screen_block[1:2]);size=int(screen_block[2:2+digits])
        screen=np.frombuffer(screen_block[2+digits:2+digits+size],dtype=np.uint8).copy()
        np.savez_compressed(path,raw=raw,preamble=pre,sample_rate_hz=rate,screen=screen,screen_preamble=screen_pre)
        if len(screen)!=1200 or abs(screen_pre[7]/(self.scale/25)-1)>.0001:
            raise ValueError('Invalid screen vertical metadata')
        screen_fit=fit_sine(screen,screen_pre,frequency)
        if abs(screen_fit['vpp_v']-fit['vpp_v'])>max(.0015,.01*fit['vpp_v']):
            raise ValueError('RAW/screen amplitude mismatch')
        values = (raw.astype(float)-pre[8]-pre[9])*pre[7]
        if shape == 'sine':
            span, center, metric = fit['vpp_v'], fit['dc_v'], 'sine_fundamental_vpp'
        elif shape == 'square':
            plateau = square_plateaus(values, pre[4], fit['frequency_hz'])
            span, center, metric = plateau['vpp_v'], plateau['dc_v'], 'square_central_plateau_mean_vpp'
        else:
            # 对多周期分相位平均，抑制随机噪声后读取三角波峰峰值。
            phases = (np.arange(len(values))*pre[4]*fit['frequency_hz']) % 1
            bins = np.minimum((phases*128).astype(int),127)
            counts = np.bincount(bins,minlength=128)
            folded = np.bincount(bins,weights=values,minlength=128)/np.maximum(counts,1)
            if counts.min()<3: raise RuntimeError('Insufficient triangle phase coverage')
            span, center, metric = float(np.ptp(folded)), float(values.mean()), 'triangle_folded_128bin_vpp'
        return dict(vpp_v=span, dc_v=center, metric=metric, raw_file=str(path.relative_to(ROOT)),
                    raw_vpp_v=float(np.ptp(values)), frequency_hz=fit['frequency_hz'],
                    residual_rms_v=fit['residual_rms_v'], thd_2_3=fit['thd_2_3'],
                    screen_fit=screen_fit,raw_screen_difference_v=fit['vpp_v']-screen_fit['vpp_v'],
                    plateau_statistics=plateau if shape=='square' else None)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--base', type=Path, default=ROOT/'build/dist/desktop_pnp_input_table_manuals_20261101/ZynqBjtDesktop/_internal')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--resume', type=Path)
    args=ap.parse_args()
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    r=dict(started=datetime.now().astimezone().isoformat(), events=[], points=[], verification=[],
           connection='TX3 direct to Rigol CH3, DC x1 high impedance; other outputs disabled',
           instrument_command_gap_s=.35, status='starting', scope_relative=True,
           amplitudes_vpp=[.05,.07,.1,.2,.5], frequencies_hz=[10000,100000,1000000])
    if args.resume:
        old=json.loads(args.resume.read_text(encoding='utf-8'))
        if not old.get('close',{}).get('cleanup_confirmed'):raise ValueError('Previous cleanup not confirmed')
        r['points']=[p for p in old['points'] if 'peak_codes' in p and
                     (p['shape']!='triangle' or p['attempts'][-1]['measurement']['metric']=='triangle_folded_128bin_vpp')]
        r['resume_source']=str(args.resume.resolve())
    s=None; a=SerialAgent('COM7','xilinx',r['events'],base=args.base)
    serial_no=0
    def save(): (out/'result.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
    def pause(seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            if (out/'stop.request').exists(): raise InterruptedError('Stop requested')
            time.sleep(min(.5,max(0,until-time.monotonic())))
    def output(shape,f,z,p):
        if not 6000<=z<=38000 or not 100<=p<=6000 or not 0<=z-p<z+p<=65535: raise ValueError('Experiment code bounds')
        state=a.call('output',dict(channel=2,action='start',mode=shape+'_code',offset=z,peak=p,
                     frequency_hz=f,phase_degrees=0,duty_percent=50,wiring_confirmed=True))
        if not state['outputs'][2]['enabled'] or any(v['enabled'] for v in state['outputs'][:2]):
            raise RuntimeError('Unexpected output state')
    def setup(f,amp):
        wanted=amp/5
        scale=next(v for v in (.01,.02,.05,.1,.2,.5) if v>=wanted)
        s.write(f':CHANnel3:SCALe {scale}');s.scale=scale;s.point(f)
        pause(2)
    def measure(shape,f,label):
        nonlocal serial_no
        for retry in range(3):
            serial_no+=1
            try:
                m=s.sample(out/f'{serial_no:04d}_{label}.npz',f,shape)
                if not .005<m['vpp_v']<1 or abs(m['dc_v'])>.3: raise RuntimeError('Unexpected TX3 voltage: '+str(m))
                return m
            except ValueError as error:
                r.setdefault('rejected',[]).append(dict(reason=str(error),record=serial_no));save()
                if retry==2:raise
                pause(3)
    try:
        s=SlowScope();r['scope_idn']=s.idn;r['scope_before']=s.prior
        r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
        if r['initialized']['identity']['dac_divider']!=8: raise RuntimeError('Expected DAC125')
        if any(v['enabled'] for v in r['initialized']['outputs']): raise RuntimeError('Expected muted startup')
        s.setup(3,sine=True,scale=.02)
        s.write(':CHANnel3:BWLimit 20M')
        if s.ask(':CHANnel3:BWLimit?')!='20M': raise RuntimeError('Bandwidth setting failed')
        # 本次直流探测已确认零点位于12000..14000，不沿用旧零点。
        r['zero_probe']=[]
        s.write(':CHANnel3:SCALe 0.2');s.scale=.2;s.write(':RUN')
        for code in (12000,14000,13000):
            a.call('output',dict(channel=2,action='start',mode='dc_code',offset=code,wiring_confirmed=True))
            pause(4)
            readings=[float(s.ask(':MEASure:ITEM? VAVG,CHANnel3')) for _ in range(5)]
            if any(not math.isfinite(v) or abs(v)>.5 for v in readings):raise RuntimeError('Zero probe outside local range')
            r['zero_probe'].append(dict(code=code,volts=float(np.mean(readings)),readings=readings));save()
        slope=(r['zero_probe'][1]['volts']-r['zero_probe'][0]['volts'])/2000
        if not .00003<slope<.0003:raise RuntimeError('Invalid measured slope')
        zero=round(13000-r['zero_probe'][2]['volts']/slope)
        r['zero_slope_v_per_code']=slope;r['initial_zero_code']=zero
        output('sine',100000,zero,round(.07/(2*slope)));setup(100000,.5)
        r['status']='warming';r['warmup']=[];save()
        for i in range(3 if args.quick or args.resume else 9):
            pause(15)
            m=measure('sine',100000,'warm')
            r['warmup'].append(m);save();print('WARM',i,round(m['vpp_v'],6),round(m['dc_v'],6),flush=True)
        # 先只调整零点，后续每点都有独立校正与复测。
        zero=round(zero-r['warmup'][-1]['dc_v']/slope)
        r['status']='calibrating';save()
        frequencies=[100000] if args.quick else r['frequencies_hz']
        amplitudes=[.07] if args.quick else r['amplitudes_vpp']
        for shape in ('sine','square','triangle'):
            for f in frequencies:
                for amp in amplitudes:
                    if any(p['shape']==shape and p['frequency_hz']==f and p['target_vpp_v']==amp for p in r['points']):continue
                    peak=round(amp/(2*slope));setup(f,amp)
                    row=dict(shape=shape,frequency_hz=f,target_vpp_v=amp,attempts=[])
                    r['points'].append(row)
                    for attempt in range(3):
                        output(shape,f,zero,peak);pause(3)
                        m=measure(shape,f,'adjust')
                        row['attempts'].append(dict(zero_code=zero,peak_codes=peak,measurement=m));save()
                        if abs(m['vpp_v']-amp)<=max(.0008,amp*.008) and abs(m['dc_v'])<=.003: break
                        peak=round(peak*amp/m['vpp_v']);zero=round(zero-m['dc_v']/slope)
                    row.update(zero_code=row['attempts'][-1]['zero_code'],peak_codes=row['attempts'][-1]['peak_codes'])
                    print('CAL',shape,f,amp,round(m['vpp_v'],6),round(m['dc_v'],6),flush=True);save()
        r['status']='verifying';save()
        for row in reversed(r['points']):
            shape,f,amp=row['shape'],row['frequency_hz'],row['target_vpp_v']
            setup(f,amp);output(shape,f,row['zero_code'],row['peak_codes']);pause(4)
            m=measure(shape,f,'verify')
            passed=abs(m['vpp_v']-amp)<=max(.0015,amp*.02) and abs(m['dc_v'])<=.005
            r['verification'].append(dict(shape=shape,frequency_hz=f,target_vpp_v=amp,measurement=m,
                amplitude_error_v=m['vpp_v']-amp,passed=passed,zero_code=row['zero_code'],peak_codes=row['peak_codes']))
            print('VERIFY',shape,f,amp,round(m['vpp_v'],6),round(m['dc_v'],6),passed,flush=True);save()
        r['status']='complete';r['passed']=all(v['passed'] for v in r['verification'])
    except BaseException as error:
        r['status']='incomplete';r['error']=repr(error);print('STOP',repr(error),flush=True)
    finally:
        try:r['close']=a.close()
        except Exception as error:r['close_error']=repr(error)
        if s:
            try:s.write(':RUN');s.s.close()
            except Exception as error:r['scope_close_error']=repr(error)
        r['finished']=datetime.now().astimezone().isoformat();save()
        print('DONE',r['status'],r.get('close'),flush=True)
    return 0 if r.get('passed') and r.get('close',{}).get('cleanup_confirmed') else 1


if __name__=='__main__':raise SystemExit(main())
