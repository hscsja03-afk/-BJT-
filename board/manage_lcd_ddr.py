"""Stage/check the separate DDR LCD candidate; never overwrite production boot files."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))


def main():
    import paramiko
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--stage-only',action='store_true')
    mode.add_argument('--restore',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    password=os.environ.get('PYNQ_SSH_PASSWORD') or getpass.getpass('PYNQ password: ')
    client=paramiko.SSHClient();client.load_host_keys(str(ROOT/'measurements/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    remote='/home/xilinx/.zynq_bjt_lcd_ddr_20261103'
    report=dict(passed=False,remote=remote,stage_only=args.stage_only)
    try:
        client.connect('192.168.0.4',username='xilinx',password=password,look_for_keys=False,allow_agent=False,timeout=10)
        if not args.restore:
            from zynq_bjt.lcd import LcdDemo,frame_pixels
            build=ROOT/'build/work/lcd_ddr_final_20261103'
            if 'sta=passed' not in (build/'build_status.txt').read_text():raise RuntimeError('Candidate STA has not passed')
            package=ROOT/'build/dist/desktop_lcd_ddr_20261103/ZynqBjtDesktop/_internal'
            files={name:(build/name).read_bytes() for name in ('bjt.bit','bjt.hwh')}
            files.update({'agent.pyz':(package/'agent.pyz').read_bytes(),
                          'check.py':(ROOT/'board/lcd_ddr_check.py').read_bytes()})
            for i in (0,1,2):
                model=LcdDemo(rgb565=True);model.has_data=True;model.phase=i*.3
                model.note='DDR 显示测试 · 模拟波形'
                files['preview%d.rgb565'%i]=frame_pixels(model.render())
            previous={}
            for path,local in [('/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit','adc625_mmcm_20261102'),
                               ('/home/xilinx/.zynq_bjt_lcd_native_20261102/bjt.bit','lcd_native_20261102')]:
                previous[path]={ext:hashlib.sha256((ROOT/'build/work'/local/('bjt.'+ext)).read_bytes()).hexdigest() for ext in ('bit','hwh')}
            manifest=dict(production='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit',previous=previous,
                          files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
            files['manifest.json']=json.dumps(manifest,indent=2).encode()
            with client.open_sftp() as sftp:
                try:sftp.stat(remote)
                except FileNotFoundError:sftp.mkdir(remote)
                for name,data in files.items():
                    with sftp.open(remote+'/'+name,'wb') as stream:stream.write(data)
                    with sftp.open(remote+'/'+name,'rb') as stream:
                        if hashlib.sha256(stream.read()).digest()!=hashlib.sha256(data).digest():raise RuntimeError('Readback mismatch: '+name)
            report['manifest']=manifest
        if args.stage_only:report['passed']=True
        else:
            program='source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u '+shlex.quote(remote+'/check.py')+' '+shlex.quote(remote+'/manifest.json')+(' --restore' if args.restore else '')
            stdin,stdout,stderr=client.exec_command('sudo -S -p "" bash -c '+shlex.quote(program),timeout=180)
            stdin.write(password+'\n');stdin.flush();password=None
            report['stdout']=stdout.read().decode();report['stderr']=stderr.read().decode()
            report['exit_code']=stdout.channel.recv_exit_status()
            with client.open_sftp() as sftp:
                with sftp.open(remote+('/restore.json' if args.restore else '/hardware.json')) as stream:report['board']=json.loads(stream.read().decode())
            report['passed']=report['exit_code']==0 and report['board']['passed']
    except Exception as error:report['error']=repr(error)
    finally:
        client.close();args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('stdout','manifest')},ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
