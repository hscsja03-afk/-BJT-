"""Verify captured data and generate ADC, DAC and transistor comparison tables."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/python'))


def sha(content):
    return hashlib.sha256(content).hexdigest()


class Captures:
    """Read measured files from the repository or its verified data archives."""

    def __init__(self):
        manifest = json.loads((ROOT / 'build/archive_manifest.json').read_text(encoding='utf-8'))
        self.members = {entry['path']: (group, entry)
                        for group in manifest['archives'] for entry in group['members']}
        self.open_archives = {}

    def read_bytes(self, name):
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('Invalid data path: ' + name)
        if name not in self.members:
            return ROOT.joinpath(*path.parts).read_bytes()
        group, entry = self.members[name]
        if group['id'] not in self.open_archives:
            parts = []
            for part in group['parts']:
                content = (ROOT / part['path']).read_bytes()
                if len(content) != part['bytes'] or sha(content) != part['sha256']:
                    raise ValueError('Archive part mismatch: ' + part['path'])
                parts.append(content)
            content = b''.join(parts)
            if sha(content) != group['zip_sha256']:
                raise ValueError('Archive hash mismatch: ' + group['id'])
            self.open_archives[group['id']] = zipfile.ZipFile(io.BytesIO(content))
        content = self.open_archives[group['id']].read(name)
        if len(content) != entry['bytes'] or sha(content) != entry['sha256']:
            raise ValueError('Captured file mismatch: ' + name)
        return content

    def verified(self, name, expected):
        content = self.read_bytes(name)
        if sha(content) != expected:
            raise ValueError('Data hash mismatch: ' + name)
        return content

    def read_json(self, name):
        return json.loads(self.read_bytes(name).decode('utf-8-sig'))

    def close(self):
        for archive in self.open_archives.values():
            archive.close()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def table(name, rows):
    path = ROOT / 'data/measurements/comparison' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def draw(entry, rows, state, raw_path, raw_hash):
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from zynq_bjt.lcd_records import make_plot

    matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False
    modes = {'input': '输入', 'output': '输出', 'beta': 'β', 'ac': '交流'}
    if entry['measurement'] not in modes:
        return
    modes_to_draw = [modes[entry['measurement']]] + (['Rin'] if entry['measurement'] == 'ac' else [])
    output = ROOT / 'measurements/summary_plots'
    for key in ('profile', 'measurement', 'method', 'run_id'):
        output /= entry[key]
    output.mkdir(parents=True, exist_ok=True)
    for mode in modes_to_draw:
        plot = make_plot(rows, state, mode)
        fig = Figure(figsize=(9, 5), layout='constrained')
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        for number, (points, _) in enumerate(plot['curves'], 1):
            if points:
                ax.plot(*zip(*points), '.-', lw=1, ms=3, label=str(number))
        if entry['measurement'] == 'ac':
            ax.set_xscale('log')
        ax.set(xlabel=plot['xlabel'], ylabel=plot['ylabel'],
               title=entry['profile'] + ' · ' + mode + ' · ' + entry['run_id'])
        ax.grid(alpha=.25)
        if len(plot['curves']) > 1:
            ax.legend(title='曲线', fontsize=8)
        image = output / ('rin.png' if mode == 'Rin' else 'curve.png')
        fig.savefig(image, dpi=130)
        write_json(image.with_suffix('.source.json'), {
            'data_file': raw_path, 'sha256': raw_hash, 'profile': entry['profile'],
            'measurement': entry['measurement'], 'view': mode, 'simulated': False})


def summarize(captures, plots=False):
    rx_rows = []
    rx_summary = {}
    channels = [
        ('RX1', 'rx1_dc_calibration.json', 'report/rx1_generator_nominal_20261030'),
        ('RX2', 'rx2_calibration.json', 'report/rx2_generator_nominal_20261031/capture'),
    ]
    for channel, calibration_file, directory in channels:
        cal = captures.read_json('data/' + calibration_file)
        collection = captures.read_json(directory + '/collection.json')
        for point in collection['points']:
            for frame in point.get('captures', []):
                captures.verified(directory + '/' + frame['file'], frame['sha256'])
        errors = []
        for point in cal['checks']:
            expected = point['reference_v_nominal']
            actual = point['voltage_v_nominal']
            error = actual - expected
            if abs(error - point['error_v']) >= 1e-10:
                raise ValueError('ADC error mismatch: ' + channel + '/' + point['label'])
            if point['role'] == 'validation':
                errors.append(abs(error))
            rx_rows.append(dict(channel=channel, role=point['role'], label=point['label'],
                                generator_nominal_v=expected, mean_adc_code=point['mean_code'],
                                converted_v=actual, error_v=error, reference_instrument=cal['generator_idn'],
                                sample_rate_hz=cal['sample_rate_hz'],
                                bit_sha256=cal['board_identity']['bit_sha256']))
        rx_summary[channel] = dict(validation_points=len(errors), maximum_error_v=max(errors),
                                   limit_v=cal['independent_validation']['limit_v_vs_generator_nominal'],
                                   reference='DG1032Z DC setpoint, High-Z', sample_rate_hz=cal['sample_rate_hz'])

    scope = captures.read_json('data/measurements/instruments/tx/verification.json')
    tx_rows = []
    for point in scope['verification']:
        measurement = point['measurement']
        captures.verified(measurement['raw_file'], measurement['raw_sha256'])
        error = measurement['vpp_v'] - point['target_vpp_v']
        if abs(error - point['amplitude_error_v']) >= 1e-10:
            raise ValueError('DAC amplitude error mismatch: ' + measurement['raw_file'])
        tx_rows.append(dict(channel='TX' + str(point['channel']), waveform=point['shape'],
                            target_frequency_hz=point['frequency_hz'], measured_frequency_hz=measurement.get('frequency_hz'),
                            target_vpp_v=point['target_vpp_v'], measured_vpp_v=measurement['vpp_v'],
                            error_v=error, error_percent=error / point['target_vpp_v'] * 100,
                            target_offset_v=point['offset_v'], measured_offset_v=measurement['dc_v'],
                            offset_error_v=measurement['dc_v'] - point['offset_v'],
                            amplitude_passed=point['amplitude_passed'], offset_passed=point['dc_passed'],
                            recorded_passed=point['passed'], metric=measurement.get('metric', ''),
                            raw_file=measurement['raw_file'], raw_sha256=measurement['raw_sha256'],
                            bit_sha256=scope['initialized']['identity']['bit_sha256']))

    run_rows = []
    for entry in captures.read_json('data/measurements/run_index.json'):
        state = json.loads(captures.verified(entry['record'], entry['record_sha256']).decode('utf-8-sig'))
        if state['simulated'] is not False or entry['simulated'] is not False:
            raise ValueError('Expected measured data: ' + entry['record'])
        files = {}
        for item in entry['data_files']:
            files[PurePosixPath(item['path']).name] = (item, captures.verified(item['path'], item['sha256']))
        preferred = {'input': 'points.csv', 'output': 'output_points.csv', 'beta': 'beta_points.csv',
                     'ac': 'points.csv', 'polarity': 'points.csv'}
        item, content = files.get(preferred[entry['measurement']], next(iter(files.values())))
        rows = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
        if any(row.get('simulated', '').lower() not in ('false', '0', '') for row in rows):
            raise ValueError('Expected measured CSV: ' + item['path'])
        run_rows.append(dict(profile=entry['profile'], measurement=entry['measurement'], method=entry['method'],
                             run_id=entry['run_id'], recorded_points=entry['points'], csv_rows=len(rows),
                             started_at=entry['started_at'], data_file=item['path'], sha256=sha(content)))
        if plots:
            draw(entry, rows, state, item['path'], sha(content))

    summary = dict(transistor_runs=len(run_rows), adc=rx_summary,
                   dac=dict(comparisons=len(tx_rows), amplitude_passed=sum(row['amplitude_passed'] for row in tx_rows),
                            offset_passed=sum(row['offset_passed'] for row in tx_rows),
                            recorded_passed=sum(row['recorded_passed'] for row in tx_rows),
                            maximum_absolute_amplitude_error_v=max(abs(row['error_v']) for row in tx_rows),
                            scope=scope['scope_idn'], captured_at=scope['finished'],
                            board_identity=scope['initialized']['identity']))
    table('adc_dc.csv', rx_rows)
    table('dac_scope.csv', tx_rows)
    table('bjt_runs.csv', run_rows)
    write_json(ROOT / 'report/measurements/summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plots', action='store_true', help='Write measured curves to measurements/summary_plots/')
    args = parser.parse_args()
    captures = Captures()
    try:
        summary = summarize(captures, plots=args.plots)
    finally:
        captures.close()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
