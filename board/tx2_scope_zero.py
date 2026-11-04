"""Compare muted TX2 and small DC setpoints using UART control plus LAN scope.

Uses the existing desktop agent, including its 12-second heartbeat lease.
Only --load-overlay reloads the existing verified PL after a cold boot.
Does not change calibration, GPIO routing, or boot storage.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import queue
import shlex
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'build/tool_deps/serial_runtime'))
import serial
from read_scope import vxi11, read_scope


class SerialAgent:
    def __init__(self, port, password, events, load_overlay=False, base=None, bitfile=None):
        self.uart = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=3)
        self.uart.dtr = self.uart.rts = False
        self.uart.port = port
        self.events, self.responses = events, queue.Queue()
        self.lock, self.ended = threading.Lock(), threading.Event()
        self.number = 0
        self.started = False
        self.password = password
        self.load_overlay = load_overlay
        self.base = Path(base) if base is not None else ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal'
        self.bitfile=bitfile

    def write(self, value):
        with self.lock:
            self.uart.write(value); self.uart.flush()

    def connect(self):
        base = self.base
        data = {p.name:p.read_bytes() for p in (base/'data').glob('*.json')}
        archive = (base/'agent.pyz').read_bytes()
        digest = hashlib.sha256(archive+b''.join(data[n] for n in sorted(data))).hexdigest()[:20]
        remote = '/home/xilinx/.zynq_bjt_desktop/'+digest
        self.uart.open()
        self.write(b'stty -echo -onlcr\n')
        time.sleep(.3)
        self.uart.read(self.uart.in_waiting)
        prepare = 'python /home/xilinx/verify_pynq_linux.py || exit $?; ' if self.load_overlay else ''
        program = ('source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; '+prepare+
                   'printf "\\nTX2_AGENT_READY\\n"; exec python -u '+shlex.quote(remote+'/agent.pyz')+
                   ' --data '+shlex.quote(remote+'/data')+
                   ' --results /home/xilinx/.zynq_bjt_desktop/results'+
                   (' --bitfile '+shlex.quote(self.bitfile) if self.bitfile else ''))
        command = ("sudo -S -p 'TX2_SUDO_PASSWORD:' bash -c "+shlex.quote(program)+
                   "; stty echo onlcr; printf '\\nTX2_SERIAL_DONE\\n'\n")
        self.write(command.encode())
        received = bytearray(); deadline = time.monotonic()+20; supplied = False
        while time.monotonic() < deadline:
            received.extend(self.uart.read(self.uart.in_waiting or 1))
            if b'TX2_SUDO_PASSWORD:' in received and not supplied:
                self.write((self.password+'\n').encode()); supplied = True
            if b'\nTX2_AGENT_READY\n' in received:
                self.started = True
                break
            if b'TX2_SERIAL_DONE' in received:
                raise RuntimeError('Board agent failed to start')
        if not self.started:
            raise TimeoutError('No board agent readiness marker over UART')
        self.password = None
        threading.Thread(target=self.receive, daemon=True).start()
        threading.Thread(target=self.heartbeat, daemon=True).start()
        return {'agent_sha256':hashlib.sha256(archive).hexdigest(), 'remote':remote,
                'overlay_reloaded':self.load_overlay,
                'status':self.call('status')}

    def receive(self):
        try:
            while not self.ended.is_set():
                line = self.uart.readline().decode('utf-8',errors='replace').strip()
                if not line: continue
                if line == 'TX2_SERIAL_DONE':
                    self.ended.set(); break
                if not line.startswith('ZBJT1 '): continue
                message = json.loads(line[6:])
                if 'event' in message:
                    if message['event'] != 'heartbeat': self.events.append(message)
                else: self.responses.put(message)
        except Exception as error:
            self.events.append({'transport_error':repr(error)})
            self.ended.set()

    def heartbeat(self):
        while not self.ended.wait(2):
            try: self.write(b'{"op":"heartbeat"}\n')
            except Exception:
                self.ended.set(); break

    def call(self, op, args=None, timeout=30):
        self.number += 1
        number = self.number
        self.write((json.dumps({'id':number,'op':op,'args':args or {}})+'\n').encode())
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try: response = self.responses.get(timeout=min(.2,max(.001,deadline-time.monotonic())))
            except queue.Empty:
                if self.ended.is_set(): raise ConnectionError('Board UART agent ended')
                continue
            if response.get('id') != number: continue
            if not response.get('ok'): raise RuntimeError(response.get('error'))
            return response.get('value')
        raise TimeoutError('Board command timed out: '+op)

    def close(self):
        result = None
        try:
            if self.started and not self.ended.is_set(): result = self.call('close',timeout=30)
            self.ended.wait(2)
        finally:
            self.ended.set()
            self.uart.close()
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',default='COM7')
    parser.add_argument('--scope-ip',default='169.254.1.5')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--volts',type=float,nargs='+',default=[0])
    parser.add_argument('--load-overlay',action='store_true')
    args = parser.parse_args()
    if not 1 <= len(args.volts) <= 4 or any(not 0 <= v <= .1 for v in args.volts):
        parser.error('Diagnostic limited to 1-4 points within 0 to 0.1 V')
    evidence = {'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
                'physical_connection':'User confirmed scope CH3 on ADDA TX2 connector',
                'events':[], 'procedure_completed':False, 'requested_voltages_v':args.volts,
                'points':[], 'analog_calibration_qualified':False}
    agent = SerialAgent(args.port,os.environ['PYNQ_SSH_PASSWORD'],evidence['events'],args.load_overlay)
    scope = vxi11.Instrument(args.scope_ip); scope.timeout=5
    def sample(label):
        readings=[]
        for _ in range(7):
            time.sleep(.15)
            value=float(scope.ask(':MEASure:ITEM? VAVG,CHANnel3'))
            if not -10 < value < 10: raise RuntimeError('Invalid/clipped scope measurement')
            readings.append(value)
        prefix=args.report.with_name(args.report.stem+'_'+label)
        state=read_scope(args.scope_ip,3,prefix,evidence['physical_connection'],scope=scope)
        return {'readings_v':readings, 'mean_v':sum(readings)/len(readings),'scope':state}
    try:
        evidence['scope_idn']=scope.ask('*IDN?').strip()
        if 'DS1104Z,DS1ZA173719283,' not in evidence['scope_idn']: raise RuntimeError('Wrong scope')
        expected={':CHANnel3:COUPling?':'DC',':CHANnel3:INVert?':'0',':CHANnel3:DISPlay?':'1'}
        if any(scope.ask(q).strip()!=v for q,v in expected.items()): raise RuntimeError('CH3 must be on, DC and non-inverted')
        if float(scope.ask(':CHANnel3:PROBe?'))!=1: raise RuntimeError('CH3 must be x1')
        if scope.ask(':TRIGger:STATus?').strip()=='STOP': raise RuntimeError('Scope must be acquiring fresh samples')
        evidence['connected']=agent.connect()
        print('UART agent connected; initializing muted.',flush=True)
        evidence['initialized']=agent.call('initialize',timeout=120)
        assert all(not s['enabled'] for s in evidence['initialized']['outputs'])
        evidence['muted_before']=sample('muted_before')
        for index,volts in enumerate(args.volts):
            state=agent.call('output',dict(channel=1,action='start',mode='dc_voltage',offset=volts,wiring_confirmed=True))
            if volts==0:
                profile=json.loads((ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal/data/dac_calibration.json').read_text())
                assert state['outputs'][1]['code']==profile['channels'][1]['dc_table']['codes'][0]
            assert state['outputs'][1]['enabled']
            assert not state['outputs'][0]['enabled'] and not state['outputs'][2]['enabled']
            measurement=sample('point'+str(index))
            evidence['points'].append({'request_v':volts,'state':state,'measurement':measurement})
            print(json.dumps({'request_v':volts,'code':state['outputs'][1]['code'],'measured_v':measurement['mean_v']}),flush=True)
        evidence['stopped']=agent.call('output',dict(channel=1,action='stop'))
        assert all(not s['enabled'] for s in evidence['stopped']['outputs'])
        evidence['muted_after']=sample('muted_after')
        evidence['procedure_completed']=True
    except BaseException as error:
        evidence['error']=repr(error)
        raise
    finally:
        try: evidence['close']=agent.close()
        except Exception as error: evidence['cleanup_error']=repr(error)
        try: scope.close()
        except Exception as error: evidence['scope_close_error']=repr(error)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:(v.get('mean_v') if k in ('muted_before','zero_enabled','muted_after') else v)
                          for k,v in evidence.items() if k in ('procedure_completed','error','close','cleanup_error','muted_before','muted_after')},indent=2),flush=True)


if __name__ == '__main__': main()
