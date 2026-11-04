"""Independently verify saved muted-capture UART bytes, without board access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def crc(values):
    require(all(0 <= v <= 0xffffffff for v in values), 'Word outside uint32')
    return zlib.crc32(struct.pack('<' + 'I' * len(values), *values)) & 0xffffffff


def verify(path):
    saved = json.loads(path.read_text(encoding='utf-8-sig'))
    raw = {}
    for direction in ('tx', 'rx'):
        p = path.with_suffix('.' + direction + '.bin')
        raw[direction] = p.read_bytes()
        expected = saved[direction + '_evidence']
        require(len(raw[direction]) == expected['bytes'], direction + ' length mismatch')
        require(hashlib.sha256(raw[direction]).hexdigest() == expected['sha256'],
                direction + ' hash mismatch')
        require(raw[direction].endswith(b'\n'), direction + ' truncated final line')

    commands = []
    for line in raw['tx'].decode('ascii').splitlines():
        parts = line.split()
        require(len(parts) == 8 and parts[0] == 'C', 'Bad command line')
        values = list(map(int, parts[1:]))
        require(crc(values[:-1]) == values[-1], 'Command CRC mismatch')
        sequence, op, *args = values[:-1]
        require(op in (1, 2, 3, 6, 7, 8), 'Unexpected command in muted capture')
        if op == 2:
            require(args == [20, 20, 0, 0], 'Unexpected clock selection')
        elif op == 6:
            require(args[0] in (0, 1, 2) and args[1:] == [0, 0, 0], 'Bad output read')
        else:
            require(args == [0, 0, 0, 0], 'Unexpected arguments or GPIO mutation')
        if commands:
            require(sequence == commands[-1]['sequence'] + 1, 'Nonconsecutive command')
        commands.append(dict(sequence=sequence, op=op, args=args))

    lines = raw['rx'].decode('ascii').splitlines()
    position = 0
    responses = []
    for command in commands:
        require(position < len(lines), 'Missing reply')
        header = lines[position].split()
        position += 1
        require(len(header) == 5 and header[0] == 'R', 'Bad reply header')
        seq, status, count, checksum = map(int, header[1:])
        require(seq == command['sequence'] and 0 <= count <= 2048, 'Bad sequence/count')
        payload = []
        while len(payload) < count:
            require(position < len(lines), 'Missing payload line')
            parts = lines[position].split()
            position += 1
            require(len(parts) == 2 + min(16, count - len(payload)) and parts[0] == 'D'
                    and int(parts[1]) == len(payload), 'Bad payload order/size')
            payload.extend(int(v, 16) for v in parts[2:])
        require(crc([seq, status, count] + payload) == checksum, 'Reply CRC mismatch')
        responses.append(dict(command, status=status, values=payload))
    require(position == len(lines), 'Unmatched serial bytes')

    frames = []
    for response in responses:
        if response['op'] != 3:
            continue
        require(response['status'] == 0 and len(response['values']) == 2048, 'Bad capture')
        matches = [f for f in saved['frames'] if f['sequence'] == response['sequence']]
        require(len(matches) == 1, 'Capture missing from JSON')
        frame = matches[0]
        require(not frame['simulated'] and not frame['starts_aligned'], 'Wrong frame metadata')
        require(frame['words'][0] + frame['words'][1] == response['values'], 'JSON payload mismatch')
        channels = []
        for label, words in zip(('RX1_ADC_B', 'RX2_ADC_A'), frame['words']):
            require(len(words) == 1024 and all(0 <= v <= 0x1ffff for v in words), 'Bad ADC word')
            codes = [v & 65535 for v in words]
            channels.append(dict(channel=label, samples=len(words), minimum_code=min(codes),
                                 maximum_code=max(codes), mean_code=sum(codes) / len(codes),
                                 overrange_samples=sum(bool(v & 65536) for v in words)))
        frames.append(dict(sequence=response['sequence'], channels=channels))
    require(len(frames) == len(saved['frames']), 'Unmatched JSON frame')
    if saved['complete']:
        require(all(r['status'] == 0 for r in responses), 'Failed command in completed run')
        expected_ops = [1, 2, 6, 6, 6, 7] + [3] * len(frames) + [6, 6, 6, 8]
        require([r['op'] for r in responses] == expected_ops, 'Unexpected completed sequence')
        require(responses[0]['values'] == saved['ping'], 'PING metadata mismatch')
        require(responses[1]['values'] == saved['initialization']['measured_clock_hz'], 'Clock metadata mismatch')
        require(all(49000000 <= r <= 51000000 for r in responses[1]['values']), 'Clock out of tolerance')
        output_reads = [r for r in responses if r['op'] == 6]
        for response, state in zip(output_reads, saved['outputs_before'] + saved['outputs_after']):
            require(response['values'] == [state['code'], 0] and state['enabled'] is False,
                    'Output readback mismatch or enabled')
        require(responses[-1]['values'] == [] and saved['cleanup_error'] is None, 'STOP not confirmed')
    return dict(trace_verified=True, capture_completed=saved['complete'],
                commands=len(commands), responses=len(responses),
                statuses=[dict(sequence=r['sequence'], op=r['op'], status=r['status']) for r in responses],
                frames=frames, outputs_enable_command_in_trace=False,
                analog_calibration_qualified=False,
                limits='Trace begins after open/identity PING. CRC and byte checks verify the recorded transport; internal-pattern success is inferred from successful audited firmware INIT, not exported per-pattern data. Output readback is digital, not an analog voltage measurement.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture_json', type=Path)
    args = parser.parse_args()
    result = verify(args.capture_json)
    output = args.capture_json.with_name(args.capture_json.stem + '_verified.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output), **result), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
