"""Run an explicitly synthetic end-to-end scan without opening hardware."""
import argparse
import csv
import json
from pathlib import Path
from .frontend import Calibration, Frontend
from .scan import ScanConfig, run_scan
from .simulation import SimulatedBoard


def plot_run(directory, output=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory = Path(directory)
    state = json.loads((directory/'run.json').read_text(encoding='utf-8'))
    with (directory/'points.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows: raise ValueError('No completed points to plot')
    fig, ax = plt.subplots(figsize=(9, 5.8), constrained_layout=True)
    curves = sorted({int(row['curve']) for row in rows})
    for curve in curves:
        selected = [row for row in rows if int(row['curve']) == curve]
        ax.plot([float(r['ube_v']) for r in selected],
                [float(r['ib_estimated_a'])*1e9 for r in selected], '.-', lw=1.5,
                label=f"UCE target {float(selected[0]['uce_target_v']):g} V")
    ax.set(xlabel='UBE (V)', ylabel='IB estimate (nA)',
           title='NPN input characteristic - '+('simulation' if state['simulated'] else 'recorded scan'))
    ax.grid(alpha=.25); ax.legend(loc='upper left')
    if state['simulated']:
        ax.text(.97, .08, 'SIMULATED DATA', transform=ax.transAxes,
                ha='right', fontsize=16, weight='bold', color='#b54d30', alpha=.8)
    fig.text(.99, .005, 'Current is a setpoint-derived estimate, not measured current.',
             ha='right', fontsize=8, color='#555555')
    output = Path(output) if output else directory/'curves.png'
    fig.savefig(output, dpi=170)
    plt.close(fig)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, default=Path('report/demo'))
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    calibration = Calibration(args.data_root)
    frontend = Frontend.load(args.data_root/'frontend.json')
    board = SimulatedBoard(calibration, frontend)
    config = ScanConfig(tx1_step_v=.04, uce_values_v=(0, 1, 3), relay_active_level=1,
                        settle_s=0, curve_settle_s=0, frame_gap_s=0)
    directory, state = run_scan(board, calibration, frontend, config, args.output)
    if state['status'] != 'complete': raise RuntimeError(state.get('error', state['status']))
    if args.plot: print(plot_run(directory))
    print(json.dumps({'directory': str(directory), 'status': state['status'],
                      'points': state['points'], 'simulated': True}, ensure_ascii=False))


if __name__ == '__main__': main()
