"""Bounded 1 V hold using the original baremetal UART firmware only."""
import json
from pathlib import Path
import re
import time
from datetime import datetime,timezone,timedelta
from tx2_scope_zero import serial

path=Path('report/tx1_reference_meter_hold_20261030.json')
stop=Path('build/work/tx1_reference_stop.flag')
if stop.exists():stop.unlink()
r={'firmware':'original archived 20261025 ELF','seconds_limit':120,'exchanges':[]}
u=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=3)
u.dtr=u.rts=False;u.port='COM7'
identified=False

def exchange(command,marker):
    u.write(command.encode());u.flush();end=time.monotonic()+5;data=bytearray()
    while time.monotonic()<end:
        data.extend(u.read(u.in_waiting or 1))
        if marker.encode() in data:
            time.sleep(.15);data.extend(u.read(u.in_waiting));break
    text=data.decode(errors='replace')
    r['exchanges'].append({'command':command,'reply':text})
    if marker not in text:raise RuntimeError('Missing reply for '+command+': '+text)
    return text

try:
    u.open();r['pending_uart']=u.read(u.in_waiting).decode(errors='replace')
    exchange('?','TX1:');identified=True
    exchange('i','TX1 result=0 ready=1 waveform=0')
    exchange('j','TX1 result=0 ready=1 waveform=0')
    text=exchange('r','TX1 result=0 ready=1 waveform=0')
    regs={int(a):int(v,16) for a,v in re.findall(r'TX1 reg(\d+)=0x([0-9a-fA-F]+)',text)}
    assert regs[1]==0x2195 and regs[8]==0x6660 and regs[3]&0x101==0 and regs[7]&1==0
    r['enabled_registers']=regs
    r['hold_started_at']=datetime.now(timezone(timedelta(hours=8))).isoformat()
    print('BAREMETAL_1V_HOLD_STARTED',r['hold_started_at'],json.dumps(regs),flush=True)
    deadline=time.monotonic()+120
    while time.monotonic()<deadline and not stop.exists():time.sleep(.2)
    r['hold_end_reason']='stop_file' if stop.exists() else '120_seconds_elapsed'
except Exception as error:
    r['error']=repr(error)
    raise
finally:
    if identified:
        for command,marker in [('q','TX1 result=0 ready=1 waveform=0'),('r','TX1 result=0 ready=1 waveform=0'),('m','DAC ONLY result=0 enabled=0')]:
            try:
                text=exchange(command,marker)
                if command=='r':
                    regs={int(a):int(v,16) for a,v in re.findall(r'TX1 reg(\d+)=0x([0-9a-fA-F]+)',text)}
                    r['tx1_powerdown_confirmed']=bool(regs.get(3,0)&1)
                if command=='m':r['tx23_muted_confirmed']=True
            except Exception as error:r.setdefault('cleanup_errors',[]).append(repr(error))
    u.close();r['ended_at']=datetime.now(timezone(timedelta(hours=8))).isoformat()
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BAREMETAL_HOLD_ENDED',r.get('tx1_powerdown_confirmed'),r.get('tx23_muted_confirmed'),flush=True)
