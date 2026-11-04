"""Temporary diagnostic archive entry; never installed as the startup driver."""
import argparse
import time
from zynq_bjt.desktop_session import Session
from zynq_bjt.desktop_agent import serve


class DiagnosticSession(Session):
    def dispatch(self, operation, request=None, emit=lambda kind, value: None):
        if operation == 'tx1_diagnostics':
            board = self.require_board()
            with board.lock:
                tx = board.tx1
                mode = (request or {}).get('mode', 'read')
                if mode == 'ldac':
                    tx.transfer(5, 0x10)
                elif mode == 'exact_config':
                    # Only documented fields; output muted while reference/range change.
                    tx.transfer(3, 1)
                    tx.transfer(2, 0)
                    tx.transfer(4, 0x0101)
                    tx.transfer(3, 0)
                elif mode == 'sync_load':
                    tx.transfer(2, 1)
                    tx.transfer(5, 0x10)
                elif mode in ('busywait_2us', 'sleep_100us'):
                    if mode == 'busywait_2us':
                        def pause(seconds):
                            deadline=time.perf_counter()+seconds
                            while time.perf_counter()<deadline:
                                pass
                        tx.pause=pause
                    else:
                        tx.pause=lambda seconds: time.sleep(.0001)
                    tx.transfer(2, 0)
                    tx.code(2000)
                    tx.enable(True)
                elif mode != 'read':
                    raise ValueError('Unsupported diagnostic')
                return {'mode': mode, 'registers': {str(r): tx.transfer(r) for r in (1,2,3,4,7,8)},
                        'state': tx.state()}
        return super().dispatch(operation, request, emit)


ap = argparse.ArgumentParser()
ap.add_argument('--data', required=True)
ap.add_argument('--results', required=True)
a = ap.parse_args()
raise SystemExit(0 if serve(DiagnosticSession(a.data, a.results), __import__('sys').stdin, __import__('sys').stdout) else 1)
