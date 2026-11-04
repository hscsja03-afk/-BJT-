"""TX2/CH3 and TX3/CH4 scope-relative AC calibration over separate LANs.

Never recalibrates TX1/TX2 DC, programs PL, or publishes tables automatically.
Probe attenuation is an explicit required physical-connection input.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import socket
import sys
import time

from board.calibration.tx.calibrate_tx3_multi import SlowScope
from board.instruments.read_scope import vxi11
from vxi11 import rpc
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.desktop_transport import SshTransport, agent_archive
from zynq_bjt.frontend import Calibration


def bind_scope_interface(address):
    """Bind only VXI-11 RPC sockets; leave FPGA SSH and OS routes unchanged."""
    def tcp(client):
        client.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.sock.settimeout(10)
        client.sock.bind((address, 0))
        client.sock.connect((client.host, client.port))
    def udp(client):
        client.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.sock.bind((address, 0))
        client.sock.connect((client.host, client.port))
    rpc.RawTCPClient.connect = tcp
    rpc.RawUDPClient.connect = udp


class LanScope(SlowScope):
    def __init__(self, ip, source, probe):
        bind_scope_interface(source)
        self.s = vxi11.Instrument(ip)
        self.s.timeout = 10
        self.last = 0
        self.idn = self.ask('*IDN?')
        if 'DS1104Z,DS1ZA173719283,' not in self.idn:
            self.s.close()
            raise RuntimeError('Unexpected scope identity: '+self.idn)
        self.original_running = self.ask(':TRIGger:STATus?') != 'STOP'
        keys = [f':CHANnel{i}:{k}' for i in range(1, 5) for k in
                ('DISPlay', 'PROBe', 'COUPling', 'INVert', 'BWLimit', 'SCALe', 'OFFSet')]
        keys += [':TIMebase:MODE', ':TIMebase:MAIN:SCALe', ':TIMebase:MAIN:OFFSet',
                 ':ACQuire:MDEPth', ':ACQuire:TYPE', ':TRIGger:MODE',
                 ':TRIGger:EDGe:SOURce', ':TRIGger:EDGe:SLOPe', ':TRIGger:EDGe:LEVel',
                 ':TRIGger:SWEep', ':WAVeform:SOURce', ':WAVeform:MODE', ':WAVeform:FORMat']
        self.prior = {key: self.ask(key+'?') for key in keys}
        self.channel = None
        self.depth = 12000
        self.probe = probe

    def setup(self, channel, sine=True, scale=.1):
        super().setup(channel, sine=sine, scale=scale)
        self.write(f':CHANnel{channel}:PROBe {self.probe}')
        self.write(f':CHANnel{channel}:SCALe {scale}')
        self.scale = float(self.ask(f':CHANnel{channel}:SCALe?'))
        if float(self.ask(f':CHANnel{channel}:PROBe?')) != self.probe:
            raise RuntimeError('Scope probe attenuation readback differs')

    def point(self, frequency, center=0):
        super().point(frequency,center)
        if math.isclose(frequency,5000000,rel_tol=1e-12):
            # At 500 ns/div NORM uses 200 MSa/s and distorted the 5 MHz
            # display fit by 1.9--3.0 mV. 200 ns/div gives 500 MSa/s and
            # twelve visible cycles; fixed-code RAW/NORM agreement was
            # verified without relaxing the original acceptance threshold.
            self.write(':TIMebase:MAIN:SCALe 0.0000002')

    def restore(self):
        self.write(':STOP')
        for key, value in self.prior.items():
            if key == ':ACQuire:MDEPth':
                self.write(':RUN')
            self.write(key+' '+value)
        self.write(':RUN' if self.original_running else ':STOP')


def stability(rows, target):
    t = np.array([r['elapsed_s'] for r in rows])
    v = np.array([r['vpp_v'] for r in rows])
    dc = np.array([r['dc_v'] for r in rows])
    span = float(t[-1]-t[0]) if len(t)>1 else 0
    slope = float(np.polyfit(t-t[0], v, 1)[0]*60) if span else None
    dc_slope = float(np.polyfit(t-t[0], dc, 1)[0]*60) if span else None
    spread = float(np.ptp(v))
    amplitude_stable = (len(t)>=6 and span>=90 and spread<=max(.0007, target*.01)
                        and abs(slope)<=max(.0003, target*.003))
    return dict(samples=len(t), span_s=span, vpp_spread_v=spread,
                dc_spread_v=float(np.ptp(dc)), vpp_slope_v_per_minute=slope,
                dc_slope_v_per_minute=dc_slope,
                dc_stable=bool(span>=90 and np.ptp(dc)<=.002 and abs(dc_slope)<=.001),
                amplitude_stable=bool(amplitude_stable))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--probe', type=int, choices=(1, 10), required=True)
    parser.add_argument('--scope', default='169.254.1.5')
    parser.add_argument('--source', default='169.254.3.254')
    parser.add_argument('--bitfile', default='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit')
    parser.add_argument('--channel', type=int, choices=(2, 3), nargs='+', default=[2, 3])
    parser.add_argument('--tx2-scope-channel',type=int,choices=(1,2,3,4),default=3)
    parser.add_argument('--tx3-scope-channel',type=int,choices=(1,2,3,4),default=4)
    parser.add_argument('--check-only', action='store_true', help='One waveform per shape; no table fitting')
    parser.add_argument('--resume',type=Path,help='Reuse prior candidate codes, with fresh warm-up and reverse verification')
    parser.add_argument('--keep-completed-shapes',action='store_true',help='Retain fully verified shapes from the matching source acquisition')
    parser.add_argument('--amplitude-only',action='store_true',help='Record center without optimizing or qualifying it')
    args = parser.parse_args()
    if args.tx2_scope_channel==args.tx3_scope_channel:
        parser.error('TX2 and TX3 must use distinct scope channels')
    scope_channels={2:args.tx2_scope_channel,3:args.tx3_scope_channel}
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    backup = out/'data_before'
    backup.mkdir()
    for name in ('dac_calibration.json', 'tx2_waveform_calibration.json', 'tx3_waveform_calibration.json'):
        shutil.copy2(ROOT/'data'/name, backup/name)
    report = dict(started=datetime.now().astimezone().isoformat(), status='starting',
                  scope_relative=True, probe=args.probe, connection={f'TX{k}':v for k,v in scope_channels.items()},
                  scope_source_address=args.source, points=[], verification=[], warmup={},
                  tx1_waveforms='unsupported_by_current_firmware', dc_calibration_changed=False,
                  fixed_code_criteria=dict(minimum_span_s=90, minimum_samples=6,
                    vpp_spread_floor_v=.0007, vpp_spread_fraction=.01,
                    slope_floor_v_per_minute=.0003, slope_fraction_per_minute=.003),
                  scope_bandwidth='OFF', square_duty_percent=50,
                  scope_5mhz_timebase_s=2e-7,
                  target_amplitudes_vpp=[.05,.07,.1,.2,.5],
                  frequencies_hz={'sine':[10000,100000,1000000,2000000,5000000],
                                  'square':[10000,100000,1000000],
                                  'triangle':[10000,100000,1000000]})
    report['center_is_acceptance_criterion']=not args.amplitude_only
    def save():
        (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    prior=None
    completed_shapes=set()
    if args.resume:
        prior=json.loads(args.resume.read_text(encoding='utf8'))
        if not prior.get('cleanup_confirmed'):raise ValueError('Prior acquisition cleanup is not confirmed')
        if (ROOT/'data/dac_calibration.json').read_bytes()!=(args.resume.parent/'data_before/dac_calibration.json').read_bytes():
            raise ValueError('DC table changed; cannot reuse prior TX2 codes')
        for name in ('tx2_waveform_calibration.json','tx3_waveform_calibration.json'):
            original=args.resume.parent/'data_before'/name
            if original.exists() and original.read_bytes()!=(ROOT/'data'/name).read_bytes():
                raise ValueError('Waveform table changed since prior acquisition: '+name)
        report['resume_source']=dict(file=str(args.resume.resolve()),sha256=hashlib.sha256(args.resume.read_bytes()).hexdigest(),
            previous_status=prior['status'],previous_cleanup_confirmed=prior.get('cleanup_confirmed',False),
            verification_repeated=not args.keep_completed_shapes,
            verification_policy='retain completed shapes; independently revisit remaining shapes' if args.keep_completed_shapes else 'independently revisit all reused candidates')
        for row in prior['points']:
            if row.get('channel') not in args.channel or not row.get('attempts'):
                continue
            last=row['attempts'][-1]
            if (row.get('zero_code')!=last['zero_code'] or row.get('peak_codes')!=last['peak_codes']
                    or abs(last['measurement']['vpp_v']-row['target_vpp_v'])>max(.0015,.02*row['target_vpp_v'])):
                continue
            kept=copy.deepcopy(row);kept['reused_candidate']=True
            if hashlib.sha256((ROOT/last['measurement']['raw_file']).read_bytes()).hexdigest()!=last['measurement']['raw_sha256']:
                raise ValueError('Candidate RAW file changed')
            report['points'].append(kept)
        if args.keep_completed_shapes:
            if prior['connection']!=report['connection'] or prior['probe']!=args.probe:
                raise ValueError('Cannot retain verification after a wiring/attenuation change')
            for ch in args.channel:
                for shape,frequencies in report['frequencies_hz'].items():
                    expected={(f,a) for f in frequencies for a in report['target_amplitudes_vpp']}
                    rows=[r for r in prior['verification'] if r['channel']==ch and r['shape']==shape]
                    if len(rows)!=len(expected) or {(r['frequency_hz'],r['target_vpp_v']) for r in rows}!=expected:
                        continue
                    if not all(r['amplitude_passed'] and (args.amplitude_only or r['dc_passed']) for r in rows):
                        continue
                    for r in rows:
                        if hashlib.sha256((ROOT/r['measurement']['raw_file']).read_bytes()).hexdigest()!=r['measurement']['raw_sha256']:
                            raise ValueError('Retained verification RAW file changed')
                    completed_shapes.add((ch,shape))
                    report['verification'].extend(copy.deepcopy(rows))
                    report['warmup'][f'TX{ch}_{shape}']=copy.deepcopy(prior['warmup'][f'TX{ch}_{shape}'])
            report['retained_verified_shapes']=[list(item) for item in sorted(completed_shapes)]
    def pause(seconds):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            if (out/'stop.request').exists():
                raise InterruptedError('Stop requested')
            time.sleep(min(.5, max(0,end-time.monotonic())))
    cal = Calibration(ROOT/'data')
    agent = SshTransport()
    scope = None
    sequence = 0
    def output(channel, shape, frequency, zero, peak):
        if not (0<=zero-peak<zero+peak<=65535 and 20<=peak<=8000):
            raise ValueError('Calibration code bounds exceeded')
        status = agent.call('output', dict(channel=channel-1, action='start',
             mode=shape+'_code', offset=zero, peak=peak, frequency_hz=frequency,
             phase_degrees=0, duty_percent=50, wiring_confirmed=True))
        if not status['outputs'][channel-1]['enabled'] or any(
                x['enabled'] for i,x in enumerate(status['outputs']) if i!=channel-1):
            raise RuntimeError('Unexpected simultaneous output')
    def setup(frequency, amplitude, center):
        # Scope's voltage scale includes the explicitly confirmed probe ratio.
        scale = next(v for v in (.01,.02,.05,.1,.2,.5,1.) if v>=max(amplitude/5,.001*args.probe))
        scope.write(f':CHANnel{scope.channel}:SCALe {scale}')
        scope.scale = float(scope.ask(f':CHANnel{scope.channel}:SCALe?'))
        scope.point(frequency, center)
        pause(1)
    def measure(shape, frequency, center, label):
        nonlocal sequence
        for retry in range(3):
            sequence += 1
            path = out/f'{sequence:04d}_{label}.npz'
            try:
                m = scope.sample(path, frequency, shape)
                if not .005<m['vpp_v']<1.2 or abs(m['dc_v']-center)>.25:
                    raise RuntimeError('Unexpected voltage; verify physical wiring/attenuation')
                m['raw_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                return m
            except (ValueError, AssertionError) as error:
                report.setdefault('rejected',[]).append(dict(file=str(path), reason=str(error)))
                save()
                if retry==2:
                    raise
                pause(2)
    try:
        scope = LanScope(args.scope, args.source, args.probe)
        report.update(scope_idn=scope.idn, scope_before=scope.prior)
        save()
        print('SCOPE',scope.idn,flush=True)
        report['connected'] = agent.connect('192.168.0.4','xilinx','xilinx',
             ROOT/'measurements/known_hosts', ROOT/'data', agent_archive(ROOT/'src/python/zynq_bjt'),
             bitfile=args.bitfile)
        save()
        print('FPGA_CONNECTED',flush=True)
        report['initialized'] = agent.call('initialize')
        save()
        print('FPGA_INITIALIZED',report['initialized']['identity']['dac_divider'],flush=True)
        if report['initialized']['identity']['dac_divider']!=8:
            raise RuntimeError('Expected DAC125; refusing calibration at a different clock')
        if prior and any(report['initialized']['identity'][key]!=prior['initialized']['identity'][key]
                         for key in ('bit_sha256','hwh_sha256','dac_divider')):
            raise RuntimeError('Hardware identity changed; prior codes cannot be resumed')
        agent.call('stop')
        for channel in args.channel:
            agent.call('stop')
            scope.setup(scope_channels[channel], scale=.2)
            center = .9 if channel==2 else 0.
            slope = ((.2/(cal.dac_code(1,1.)[0]-cal.dac_code(1,.8)[0])) if channel==2
                     else cal.dac['channels'][2]['reference_uv']/1e6/cal.dac['channels'][2]['reference_codes'])
            for shape in ('sine','square','triangle'):
                if (channel,shape) in completed_shapes:
                    print('KEEP_VERIFIED_SHAPE',channel,shape,flush=True)
                    continue
                if channel==2:
                    zero = cal.dac_code(1,center)[0]
                    peak = round(.2/(2*abs(slope)))
                else:
                    plan = cal.waveform_parameters(shape,100000,.2)
                    zero,peak = round(plan['zero_code']),round(plan['peak_codes'])
                candidate=next((r for r in report['points'] if r.get('reused_candidate') and r['channel']==channel
                    and r['shape']==shape and r['frequency_hz']==100000 and r['target_vpp_v']==.2),None)
                if candidate:zero,peak=candidate['zero_code'],candidate['peak_codes']
                view_center=center
                setup(100000,.5,center)
                output(channel,shape,100000,zero,peak)
                pause(3)
                initial = measure(shape,100000,center,f'tx{channel}_{shape}_initial')
                report['points'].append(dict(channel=channel,shape=shape,stage='initial',
                    zero_code=zero,peak_codes=peak,measurement=initial))
                print('INITIAL',channel,shape,initial['vpp_v'],initial['dc_v'],flush=True)
                save()
                if args.check_only:
                    continue
                if args.amplitude_only:
                    # Center the scope view, not the output or its DC table.
                    view_center=initial['dc_v']
                setup(100000,.2,view_center)
                # Fixed-code warm-up: no chasing drift while determining stability.
                key=f'TX{channel}_{shape}'
                warm=[]
                report['warmup'][key]=dict(zero_code=zero,peak_codes=peak,rows=warm,scope_scale_v=scope.scale,scope_center_v=view_center)
                start=time.monotonic()
                while len(warm)<6 or time.monotonic()-start<100:
                    pause(12)
                    m=measure(shape,100000,center,f'tx{channel}_{shape}_warm')
                    warm.append(dict(m,elapsed_s=time.monotonic()-start))
                    print('WARM',channel,shape,len(warm),m['vpp_v'],m['dc_v'],flush=True)
                    save()
                report['warmup'][key]['stability']=stability(warm,initial['vpp_v'])
                if channel==3 and not args.amplitude_only:
                    # Align the waveform center while still using the broad
                    # view, before narrowing the scale for the 50 mVpp points.
                    trims=[]
                    report['warmup'][key]['center_trim']=trims
                    for attempt in range(4):
                        m=warm[-1] if attempt==0 else measure(shape,100000,center,f'tx{channel}_{shape}_center')
                        trims.append(dict(zero_code=zero,peak_codes=peak,measurement=m))
                        save()
                        if abs(m['dc_v'])<=.003:
                            break
                        zero=round(zero-m['dc_v']/slope)
                        output(channel,shape,100000,zero,peak)
                        pause(3)
                report['status']='calibrating'
                for frequency in report['frequencies_hz'][shape]:
                    for amplitude in report['target_amplitudes_vpp']:
                        if any(r.get('reused_candidate') and r['channel']==channel and r['shape']==shape
                               and r['frequency_hz']==frequency and r['target_vpp_v']==amplitude for r in report['points']):
                            print('REUSE_CANDIDATE',channel,shape,frequency,amplitude,flush=True)
                            continue
                        peak=round(amplitude/(2*abs(slope)))
                        if channel==3:
                            seed=cal.waveform_parameters(shape,frequency,amplitude)
                            peak=round(seed['peak_codes'])
                        setup(frequency,amplitude,view_center)
                        row=dict(channel=channel,shape=shape,frequency_hz=frequency,
                            target_vpp_v=amplitude,offset_v=center,attempts=[])
                        report['points'].append(row)
                        for attempt in range(4):
                            output(channel,shape,frequency,zero,peak)
                            pause(2)
                            m=measure(shape,frequency,center,f'tx{channel}_{shape}_adjust')
                            row['attempts'].append(dict(zero_code=zero,peak_codes=peak,measurement=m))
                            row.update(zero_code=zero,peak_codes=peak)
                            save()
                            if abs(m['vpp_v']-amplitude)<=max(.0008,amplitude*.008) and (args.amplitude_only or channel==2 or abs(m['dc_v'])<=.003):
                                break
                            peak=round(peak*amplitude/m['vpp_v'])
                            if channel==3 and not args.amplitude_only:
                                zero=round(zero-m['dc_v']/slope)
                        print('CAL',channel,shape,frequency,amplitude,m['vpp_v'],flush=True)
                # Independent reverse revisit; use stored codes without correction.
                report['status']='verifying'
                rows=[r for r in report['points'] if r['channel']==channel and r['shape']==shape and 'attempts' in r]
                for row in reversed(rows):
                    f,amp=row['frequency_hz'],row['target_vpp_v']
                    setup(f,amp,view_center)
                    output(channel,shape,f,row['zero_code'],row['peak_codes'])
                    pause(3)
                    m=measure(shape,f,center,f'tx{channel}_{shape}_verify')
                    amplitude_passed=abs(m['vpp_v']-amp)<=max(.0015,.02*amp)
                    dc_passed=abs(m['dc_v']-center)<=.005
                    report['verification'].append(dict(channel=channel,shape=shape,frequency_hz=f,
                        target_vpp_v=amp,offset_v=center,zero_code=row['zero_code'],peak_codes=row['peak_codes'],
                        measurement=m,amplitude_error_v=m['vpp_v']-amp,amplitude_passed=amplitude_passed,
                        dc_passed=dc_passed,passed=amplitude_passed and (args.amplitude_only or dc_passed)))
                    save()
                    print('VERIFY',channel,shape,f,amp,m['vpp_v'],amplitude_passed,flush=True)
        report['status']='complete'
    except BaseException as error:
        report.update(status='incomplete',error=repr(error))
        print('STOP',repr(error),flush=True)
    finally:
        if agent.alive:
            try:
                report['stopped']=agent.call('stop')
                report['closed']=agent.close()
                report['cleanup_confirmed']=not any(x['enabled'] for x in report['stopped']['outputs'])
            except Exception as error:
                report['cleanup_error']=repr(error)
                agent.abort()
        if scope:
            try:scope.restore();report['scope_restored']=True
            except Exception as error:report['scope_restore_error']=repr(error)
            finally:scope.s.close()
        report['dc_calibration_unchanged']=hashlib.sha256((backup/'dac_calibration.json').read_bytes()).digest()==hashlib.sha256((ROOT/'data/dac_calibration.json').read_bytes()).digest()
        report['finished']=datetime.now().astimezone().isoformat()
        save()
        print('DONE',report['status'],'cleanup',report.get('cleanup_confirmed'),flush=True)
    return 0 if report['status']=='complete' and report.get('cleanup_confirmed') else 1


if __name__=='__main__':
    raise SystemExit(main())
