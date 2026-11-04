"""SSH stdio server; bounded command queue, cancellation and expiring PC lease."""
import argparse
import json
import queue
import sys
import threading
import time
from .desktop_session import Session, DEFAULT_BIT

PREFIX = 'ZBJT1 '


def serve(session, stream_in, stream_out, *, lease_seconds=12):
    pending = queue.Queue(maxsize=1)
    ended = threading.Event()
    write_lock = threading.Lock()
    last_contact = [time.monotonic()]
    cleanup = []
    token = [session.cancel]
    command_lock = threading.Lock()

    def cancel():
        with command_lock: token[0].set()
        session.cancel.set()

    def send(message):
        with write_lock:
            try:
                stream_out.write(PREFIX + json.dumps(message, ensure_ascii=True, allow_nan=False) + '\n')
                stream_out.flush()
            except (OSError, ValueError):
                ended.set(); cancel()

    def receive():
        try:
            for line in stream_in:
                if ended.is_set(): break
                msg = None
                try:
                    if len(line) > 2000000: raise ValueError('命令过长')
                    msg = json.loads(line)
                    op = msg['op']
                    last_contact[0] = time.monotonic()
                    if op == 'heartbeat':
                        send({'event': 'heartbeat', 'value': {}})
                        continue
                    if op == 'cancel':
                        cancel()
                        send({'event': 'cancel_requested', 'value': {}})
                        continue
                    if op == 'lcd_stream':
                        # Queue pixels only. The scan thread owns all MMIO.
                        value = session.queue_scan_lcd(msg.get('args') or {})
                        send({'id': msg.get('id'), 'ok': True, 'value': value})
                        continue
                    with command_lock:
                        next_token = threading.Event()
                        pending.put_nowait((msg, next_token))
                        token[0] = next_token
                except Exception as exc:
                    send({'id': msg.get('id') if isinstance(locals().get('msg'), dict) else None,
                          'ok': False, 'error': str(exc)})
        finally:
            ended.set(); cancel()

    def watchdog():
        while not ended.wait(.25):
            if time.monotonic() - last_contact[0] > lease_seconds:
                ended.set(); cancel()

    threading.Thread(target=receive, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        while not ended.is_set():
            try: msg, next_token = pending.get(timeout=.2)
            except queue.Empty: continue
            if ended.is_set(): break
            session.cancel = next_token
            if ended.is_set(): session.cancel.set(); break
            try:
                value = session.dispatch(msg['op'], msg.get('args'),
                    lambda kind, value: send({'event': kind, 'value': value}))
                send({'id': msg['id'], 'ok': True, 'value': value})
            except Exception as exc:
                send({'id': msg.get('id'), 'ok': False, 'error': str(exc)})
            if msg['op'] == 'close': break
    finally:
        ended.set(); session.cancel.set()
        try: session.close()
        except Exception as exc: cleanup.append(str(exc))
        send({'event': 'session_closed', 'value': {'cleanup_errors': cleanup}})
    return not cleanup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--results', required=True)
    parser.add_argument('--bitfile', default=DEFAULT_BIT)
    parser.add_argument('--simulate', action='store_true')
    args = parser.parse_args()
    session = Session(args.data, args.results, simulated=args.simulate, bitfile=args.bitfile)
    return 0 if serve(session, sys.stdin, sys.stdout) else 1


if __name__ == '__main__':
    raise SystemExit(main())
