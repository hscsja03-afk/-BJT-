"""Run an explicit script or transfer files to the directly connected PYNQ board."""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/tool_deps/ssh_runtime'))
import paramiko


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='192.168.0.4')
    parser.add_argument('--script', type=Path)
    parser.add_argument('--command')
    parser.add_argument('--sudo', action='store_true')
    parser.add_argument('--put', nargs=2, action='append', default=[])
    parser.add_argument('--get', nargs=2, action='append', default=[])
    args = parser.parse_args()
    password = os.environ.get('PYNQ_SSH_PASSWORD') or getpass.getpass('Board password: ')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    prefix = ROOT / 'build/logs' / ('pynq_ssh_' + stamp)
    client = paramiko.SSHClient()
    known = ROOT / 'build/work/pynq_jtag_boot/known_hosts'
    if known.exists():
        client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    evidence = dict(host=args.host, user='xilinx', sudo=args.sudo, put=args.put, get=args.get)
    try:
        client.connect(args.host, username='xilinx', password=password,
                       look_for_keys=False, allow_agent=False, timeout=10)
        client.save_host_keys(str(known))
        with client.open_sftp() as sftp:
            for local, remote in args.put:
                sftp.put(local, remote)
            for remote, local in args.get:
                sftp.get(remote, local)
        script = args.script.read_text(encoding='utf-8') if args.script else args.command
        code = 0
        if script:
            evidence['script'] = script
            stdin, stdout, stderr = client.exec_command('sudo -S -p "" bash -s' if args.sudo else 'bash -s', timeout=120)
            if args.sudo:
                stdin.write(password + '\n')
                stdin.flush()
            stdin.write(script + '\n')
            stdin.flush()
            stdin.channel.shutdown_write()
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            code = stdout.channel.recv_exit_status()
            evidence.update(returncode=code, stdout=out, stderr=err)
            print(out, end='')
            print(err, end='', file=sys.stderr)
        evidence['returncode'] = code
    except Exception as exc:
        evidence['error'] = str(exc)
        raise
    finally:
        client.close()
        prefix.with_suffix('.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print('SSH_EVIDENCE=' + str(prefix.with_suffix('.json')))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
