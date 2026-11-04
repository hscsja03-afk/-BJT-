"""Bounded UART capture/commands, optionally capturing a concurrent JTAG launch."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'build/tool_deps/serial_runtime'))
import serial


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM7')
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--command', action='append', default=[])
    parser.add_argument('--xsdb-script')
    parser.add_argument('--abort-autoboot', action='store_true')
    parser.add_argument('--redact-command', action='store_true', help='Do not retain sensitive input in metadata')
    parser.add_argument('--expect', help='Fail if this text is missing from received data')
    args = parser.parse_args()
    if args.xsdb_script and args.command:
        parser.error('Use a separate invocation for commands after JTAG launch')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    prefix = ROOT / 'build/logs' / ('pynq_uart_' + stamp)
    metadata = dict(started=datetime.datetime.now().astimezone().isoformat(),
                    port=args.port, baud=115200,
                    commands=['<redacted>'] * len(args.command) if args.redact_command else args.command, sent=[],
                    xsdb_script=args.xsdb_script)
    proc = None
    xsdb_log = None
    received = bytearray()
    uart = serial.Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=2)
    uart.port = args.port
    uart.dtr = False
    uart.rts = False
    try:
        uart.open()
        if args.xsdb_script:
            xsdb_log = prefix.with_suffix('.xsdb.log').open('wb')
            proc = subprocess.Popen(['cmd.exe', '/d', '/c',
                'D:/FPGA/Xilix/2026.1/Vitis/bin/xsdb.bat', args.xsdb_script],
                cwd=ROOT, stdout=xsdb_log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            metadata['xsdb_pid'] = proc.pid
        start = time.monotonic()
        next_command = 0
        last_sent = start - args.seconds
        deadline = start + args.seconds
        aborted = False
        with prefix.with_suffix('.bin').open('wb') as raw:
            while time.monotonic() < deadline:
                now = time.monotonic()
                if next_command < len(args.command) and now - last_sent >= args.seconds:
                    command = args.command[next_command]
                    uart.write((command + '\r').encode('utf-8'))
                    metadata['sent'].append('<redacted>' if args.redact_command else command)
                    next_command += 1
                    last_sent = now
                    deadline = now + args.seconds + (len(args.command) - next_command) * args.seconds
                chunk = uart.read(max(1, uart.in_waiting))
                if chunk:
                    raw.write(chunk)
                    raw.flush()
                    received.extend(chunk)
                    sys.stdout.write(chunk.decode('utf-8', errors='replace'))
                    sys.stdout.flush()
                    if args.abort_autoboot and not aborted and b'Hit any key to stop autoboot:' in received:
                        uart.write(b' ')
                        metadata['sent'].append('<space to interrupt autoboot>')
                        aborted = True
                if proc is not None and proc.poll() is not None:
                    metadata['xsdb_returncode'] = proc.returncode
                    if proc.returncode != 0:
                        raise RuntimeError('XSDB failed; inspect ' + str(prefix.with_suffix('.xsdb.log')))
        metadata['bytes_received'] = len(received)
        if args.expect and args.expect.encode('utf-8') not in received:
            raise RuntimeError('Expected UART text not received: ' + args.expect)
    except Exception as exc:
        metadata['error'] = str(exc)
        raise
    finally:
        uart.close()
        if proc is not None:
            metadata['xsdb_returncode'] = proc.poll()
            metadata['xsdb_still_running'] = proc.poll() is None
        if xsdb_log:
            xsdb_log.close()
        prefix.with_suffix('.log').write_text(received.decode('utf-8', errors='replace'), encoding='utf-8')
        metadata['ended'] = datetime.datetime.now().astimezone().isoformat()
        prefix.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        print('\nUART_EVIDENCE=' + str(prefix.with_suffix('.json')), flush=True)


if __name__ == '__main__':
    main()
