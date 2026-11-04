"""Upload and temporarily load/restore the native LCD trial through pinned SSH."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))


def main():
    import paramiko
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--preview-only',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--package',type=Path,default=ROOT/'build/dist/desktop_lcd_native_20261102/ZynqBjtDesktop/_internal')
    args=parser.parse_args()
    remote='/home/xilinx/.zynq_bjt_lcd_native_20261102'
    password=os.environ.get('PYNQ_SSH_PASSWORD') or getpass.getpass('PYNQ password: ')
    client=paramiko.SSHClient();client.load_host_keys(str(ROOT/'measurements/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    report=dict(passed=False,restore=args.restore,remote=remote)
    try:
        client.connect('192.168.0.4',username='xilinx',password=password,look_for_keys=False,allow_agent=False,timeout=10)
        if not args.restore:
            from zynq_bjt.lcd import LcdDemo
            model=LcdDemo(native=True);model.has_data=True
            model.note='原生显示预览 · 模拟波形 · 控制已暂停'
            build=ROOT/'build/work/lcd_native_20261102'
            if 'sta=passed' not in (build/'build_status.txt').read_text():
                raise RuntimeError('Candidate timing has not passed')
            files={name:(build/name).read_bytes() for name in ('bjt.bit','bjt.hwh')}
            files.update({'agent.pyz':(args.package/'agent.pyz').read_bytes(),
                          'preview.pixels':model.render().tobytes(),
                          'switch.py':(ROOT/'board/lcd/lcd_native_switch.py').read_bytes()})
            production=ROOT/'build/work/adc625_mmcm_20261102'
            manifest=dict(production='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit',
                          production_hashes={ext:hashlib.sha256((production/('bjt.'+ext)).read_bytes()).hexdigest() for ext in ('bit','hwh')},
                          files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
            files['manifest.json']=json.dumps(manifest,indent=2).encode()
            with client.open_sftp() as sftp:
                try:sftp.stat(remote)
                except FileNotFoundError:sftp.mkdir(remote)
                for name,data in files.items():
                    with sftp.open(remote+'/'+name,'wb') as stream:stream.write(data)
                    with sftp.open(remote+'/'+name,'rb') as stream:
                        if hashlib.sha256(stream.read()).digest()!=hashlib.sha256(data).digest():
                            raise RuntimeError('Upload readback failed: '+name)
            report['manifest']=manifest
        program='source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u '+shlex.quote(remote+'/switch.py')+' '+shlex.quote(remote+'/manifest.json')+(' --restore' if args.restore else ' --preview-only' if args.preview_only else '')
        stdin,stdout,stderr=client.exec_command('sudo -S -p "" bash -c '+shlex.quote(program),timeout=180)
        stdin.write(password+'\n');stdin.flush();password=None
        report['stdout']=stdout.read().decode();report['stderr']=stderr.read().decode()
        report['exit_code']=stdout.channel.recv_exit_status()
        with client.open_sftp() as sftp:
            name='restore.json' if args.restore else 'preview.json' if args.preview_only else 'load.json'
            try:
                with sftp.open(remote+'/'+name) as stream:report['board']=json.loads(stream.read().decode())
            except FileNotFoundError:pass
        report['passed']=report['exit_code']==0 and report.get('board',{}).get('passed',False)
    except BaseException as error:report['error']=repr(error)
    finally:
        client.close();args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','error','exit_code') if k in report}))
    if not report['passed']:print(report.get('stderr',''))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
