"""Measure the original baremetal TX1 UART commands; no Linux/PYNQ control."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import json
from pathlib import Path
import re
import time
from board.instruments.tx2_scope_zero import serial
from board.calibration.tx.calibrate_tx23_scope import Scope
from board.instruments.read_scope import read_scope


def main():
    report = dict(controller='original archived baremetal ELF, UART single-character commands',
                  channel=3, completed=False, points=[], exchanges=[])
    path=Path('report/tx1_reference_scope_20261030.json')
    uart=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=3)
    uart.dtr=uart.rts=False;uart.port='COM7'
    scope=None
    identified=False

    def exchange(command, marker, timeout=5):
        uart.write(command.encode('ascii'));uart.flush()
        data=bytearray();deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            data.extend(uart.read(uart.in_waiting or 1))
            if marker.encode() in data:
                time.sleep(.15);data.extend(uart.read(uart.in_waiting));break
        text=data.decode(errors='replace')
        report['exchanges'].append(dict(command=command,reply=text))
        if marker not in text:raise RuntimeError(f'No expected baremetal reply for {command!r}: {text}')
        if re.search(r'TX1 result=-\d+',text):raise RuntimeError(text)
        return text

    def registers():
        text=exchange('r','TX1 result=0 ready=1 waveform=0')
        values={int(a):int(v,16) for a,v in re.findall(r'TX1 reg(\d+)=0x([0-9a-fA-F]+)',text)}
        if set(values)!={1,2,3,4,7,8}:raise RuntimeError('Incomplete DAC register dump')
        return values

    try:
        uart.open()
        report['pending_uart']=uart.read(uart.in_waiting).decode(errors='replace')
        exchange('?','TX1:')
        identified=True
        scope=Scope();scope.setup(3,scale=.5)
        exchange('i','TX1 result=0 ready=1 waveform=0')
        for command,code in [('u',819),('j',1638),('v',2048)]:
            exchange(command,'TX1 result=0 ready=1 waveform=0')
            regs=registers()
            assert regs[1]==0x2195 and regs[8]==code<<4 and regs[3]&0x0101==0 and regs[7]&1==0
            time.sleep(.5)
            measured=scope.dc(0,repeats=5)
            report['points'].append(dict(command=command,code=code,nominal_v=code*2.5/4096,
                                         registers=regs,scope=measured))
            print('BAREMETAL_TX1_POINT',command,code,measured['mean_v'],flush=True)
            if command=='j':
                report['screenshot']=read_scope('169.254.1.5',3,Path('report/tx1_reference_1v_20261030'),
                    'User moved TX1 SMA to CH3 for original baremetal comparison',scope=scope.s)
        report['completed']=True
        report['nominal_response_max_error_v']=max(abs(p['nominal_v']-p['scope']['mean_v']) for p in report['points'])
    except Exception as error:
        report['error']=repr(error)
        raise
    finally:
        if identified:
            try:
                exchange('q','TX1 result=0 ready=1 waveform=0')
                regs=registers()
                exchange('m','DAC ONLY result=0 enabled=0')
                report['cleanup']=dict(tx1_registers=regs,tx1_powerdown_confirmed=bool(regs[3]&1),tx23_muted_confirmed=True)
            except Exception as error:report['cleanup_error']=repr(error)
        uart.close()
        if scope is not None:
            try:scope.s.close()
            except Exception as error:report['scope_close_error']=repr(error)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('BAREMETAL_TX1_REPORT',str(path),flush=True)


if __name__=='__main__':main()
