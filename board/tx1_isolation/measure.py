"""Automated voltage comparisons using only the TX1 isolation C program."""
import argparse,json,re,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tx2_scope_zero import serial
from calibrate_tx23_scope import Scope

ap=argparse.ArgumentParser();ap.add_argument('--report',type=Path,required=True);ap.add_argument('--commands',default='BPSZCB');a=ap.parse_args()
r={'points':[],'exchanges':[],'completed':False};u=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=3)
u.dtr=u.rts=False;u.port='COM7';scope=None;identified=False
def cmd(c,marker=None):
    marker=marker or 'ISOLATION_RESULT command='+c
    u.write(c.encode());u.flush();end=time.monotonic()+5;data=bytearray()
    while time.monotonic()<end:
        data.extend(u.read(u.in_waiting or 1))
        if marker.encode() in data:
            time.sleep(.1);data.extend(u.read(u.in_waiting));break
    text=data.decode(errors='replace');r['exchanges'].append({'command':c,'reply':text})
    if marker not in text or re.search(r'status=-\d+',text):raise RuntimeError(text)
    return text
try:
    u.open();u.read(u.in_waiting);cmd('?','TX1_ISOLATION_READY');identified=True
    scope=Scope();scope.setup(3,scale=.5)
    descriptions={'B':'original initialization then 1 V','P':'migrated initialization then 1 V','S':'migrated with 100 us waits','Z':'migrated zero','C':'migrated code 2000','T':'DAC soft reset then reference divide by 2','D':'direct 1 V write','0':'direct zero write','L':'LDAC trigger','F':'full SYNC clear then direct 1 V'}
    for c in a.commands:
        description=descriptions.get(c,c)
        cmd(c);text=cmd('R');time.sleep(.3)
        regs={int(k):int(v,16) for k,v in re.findall(r'TX1 reg(\d+)=0x([0-9a-fA-F]+)',text)}
        p={'command':c,'description':description,'registers':regs,'scope':scope.dc(0,repeats=5)}
        r['points'].append(p);print('ISOLATION_POINT',c,p['scope']['mean_v'],flush=True)
    r['completed']=True
finally:
    if identified:
        try:
            cmd('Q');text=cmd('R');regs={int(k):int(v,16) for k,v in re.findall(r'TX1 reg(\d+)=0x([0-9a-fA-F]+)',text)}
            r['tx1_powerdown_confirmed']=bool(regs[3]&1)
        except Exception as e:r['cleanup_error']=repr(e)
    u.close()
    if scope is not None:scope.s.close()
    a.report.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
