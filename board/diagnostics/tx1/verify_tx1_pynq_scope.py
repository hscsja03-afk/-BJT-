"""Exercise the released desktop agent on PYNQ and measure TX1 on scope CH3.

Fixture must be disconnected; TX1 is connected only to the scope. Uses the
desktop's normal output API and lease. Always closes all three outputs.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time
from board.calibration.tx.calibrate_tx23_scope import Scope
from board.instruments.tx2_scope_zero import SerialAgent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    result = dict(started=datetime.now().astimezone().isoformat(),
                  connection='TX1 SMA to CH3, DC, x1, transistor fixture disconnected',
                  events=[], points=[], passed=False, scope_relative=True,
                  calibration_changed=False)
    agent = SerialAgent('COM7', os.environ['PYNQ_SSH_PASSWORD'], result['events'])
    scope = None

    def measure(label, state, expected):
        outputs = state['outputs']
        assert not outputs[1]['enabled'] and not outputs[2]['enabled'], state
        time.sleep(.25)
        reading = scope.dc(0, repeats=5)
        point = dict(label=label, expected_nominal_v=expected, state=state, reading=reading)
        result['points'].append(point)
        print(json.dumps(dict(label=label, expected_v=expected,
                              measured_v=reading['mean_v'], output=outputs[0])), flush=True)
        # Functional acceptance, not a precision calibration claim.
        assert abs(reading['mean_v'] - expected) < .025, point

    def output(action, value=0, mode='dc_voltage'):
        return agent.call('output', dict(channel=0, action=action, mode=mode,
                                        offset=value, wiring_confirmed=True))

    try:
        scope = Scope()
        result['scope_idn'] = scope.idn
        scope.setup(3, scale=.5)
        result['connected'] = agent.connect()
        result['initialized'] = agent.call('initialize', timeout=120)
        measure('initialized_muted', result['initialized'], 0)
        for value in (.5, 1.0, 1.25):
            measure('voltage_' + str(value), output('start', value), value)
        measure('raw_code_2000', output('apply', 2000, 'dc_code'), 2000 * 2.5 / 4096)
        measure('live_zero', output('apply', 0), 0)
        measure('live_back_to_1V', output('apply', 1), 1)
        measure('stopped', output('stop'), 0)
        for value in (.5, 0, 1.25, 1):
            state = output('apply', value)
            assert not state['outputs'][0]['enabled'], state
            assert state['outputs'][0]['code_basis'] == 'pending_until_enabled', state
        measure('repeated_apply_stays_muted', state, 0)
        measure('restart_after_repeated_apply', output('start', 1), 1)
        measure('stopped_again', output('stop'), 0)
        measure('start_at_zero', output('start', 0), 0)
        measure('zero_start_then_1V', output('apply', 1), 1)
        measure('final_stop', output('stop'), 0)
        result['passed'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        try:
            result['close'] = agent.close()
            if scope is not None:
                result['after_close'] = scope.dc(0)
                assert abs(result['after_close']['mean_v']) < .025
        except Exception as error:
            result['cleanup_error'] = repr(error)
            result['passed'] = False
        if scope is not None:
            try: scope.s.close()
            except Exception as error: result['scope_close_error'] = repr(error)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: result.get(k) for k in ('passed', 'error', 'close', 'cleanup_error')}), flush=True)
    if not result['passed']:
        raise RuntimeError('PYNQ acceptance or cleanup failed')


if __name__ == '__main__':
    main()
