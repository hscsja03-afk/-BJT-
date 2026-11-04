"""Receive-only UART evidence across a physical USB/power reconnect."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[2]))

import argparse
import datetime
import json
from pathlib import Path
import sys
import time
from board.instruments.tx2_scope_zero import serial

ap = argparse.ArgumentParser()
ap.add_argument('--seconds', type=float, default=180)
args = ap.parse_args()
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
prefix = Path(__file__).resolve().parents[2] / 'build/logs' / ('qspi_coldboot_uart_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
received = bytearray()
events = []
start = time.monotonic()
uart = None
try:
    with prefix.with_suffix('.bin').open('wb') as raw:
        while time.monotonic() - start < args.seconds:
            try:
                if uart is None:
                    uart = serial.Serial(port=None, baudrate=115200, timeout=.1)
                    uart.dtr = uart.rts = False
                    uart.port = 'COM7'
                    uart.open()
                    events.append({'seconds': time.monotonic() - start, 'event': 'opened'})
                chunk = uart.read(uart.in_waiting or 1)
                if chunk:
                    received.extend(chunk)
                    raw.write(chunk)
                    raw.flush()
                    print(chunk.decode(errors='replace'), end='', flush=True)
            except (serial.SerialException, OSError) as exc:
                events.append({'seconds': time.monotonic() - start, 'event': 'port_unavailable', 'detail': str(exc)})
                if uart is not None:
                    uart.close()
                    uart = None
                time.sleep(1)
finally:
    if uart is not None:
        uart.close()
    prefix.with_suffix('.log').write_text(received.decode(errors='replace'), encoding='utf-8')
    prefix.with_suffix('.json').write_text(json.dumps({'receive_only': True, 'bytes_received': len(received), 'events': events}, indent=2), encoding='utf-8')
    print('\nCOLD_BOOT_UART_EVIDENCE=' + str(prefix.with_suffix('.json')), flush=True)
