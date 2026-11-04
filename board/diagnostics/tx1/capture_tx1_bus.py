"""Capture TX1 SCL/SDA after the user connects two x10 probes.

Default: CH2=U7-side R11/SCL; CH4=U7-side R10/SDA; no VOUT probe.
Uses production UART agent with heartbeat and closes outputs before waveform transfer.
RAW waveform samples are evidence; threshold decoding is not an SI qualification.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
from board.calibration.tx.calibrate_tx23_scope import Scope
from board.instruments.tx2_scope_zero import SerialAgent


def decode_i2c(scl_v, sda_v, dt, threshold=1.5):
    scl = np.asarray(scl_v) > threshold
    sda = np.asarray(sda_v) > threshold
    if len(scl) != len(sda) or len(scl) < 2 or dt <= 0:
        raise ValueError('Aligned nonempty voltage records and positive dt required')
    edges = np.flatnonzero((scl[1:] != scl[:-1]) | (sda[1:] != sda[:-1])) + 1
    frames, frame, bits = [], None, []
    highs, lows = [], []
    previous_clock_edge = None
    simultaneous = []
    for edge in edges:
        i = int(edge)
        clock_changed = scl[i] != scl[i-1]
        data_changed = sda[i] != sda[i-1]
        if clock_changed and data_changed:
            simultaneous.append(i)
        if not clock_changed and data_changed and scl[i]:
            if not sda[i]:
                if frame is not None:
                    frame.update(end_sample=i, end='repeated_start', trailing_bits=bits)
                frame = dict(start_sample=i, bytes=[], ack=[])
                frames.append(frame)
                bits = []
            elif frame is not None:
                frame.update(end_sample=i, end='stop', trailing_bits=bits)
                frame = None
                bits = []
        if clock_changed:
            if previous_clock_edge is not None:
                (lows if scl[i] else highs).append((i-previous_clock_edge)*dt)
            previous_clock_edge = i
            if scl[i] and frame is not None:
                bits.append(int(sda[i]))
                if len(bits) == 9:
                    value = 0
                    for bit in bits[:8]:
                        value = (value << 1) | bit
                    frame['bytes'].append(value)
                    frame['ack'].append(bits[8] == 0)
                    bits = []
    if frame is not None:
        frame.update(end='capture_end', trailing_bits=bits)
    for f in frames:
        f['hex'] = ' '.join(f'{b:02X}' for b in f['bytes'])
    return dict(frames=frames, threshold_v=threshold, sample_interval_s=dt,
                scl_high_min_s=min(highs) if highs else None,
                scl_low_min_s=min(lows) if lows else None,
                simultaneous_edge_samples=simultaneous,
                matched_code2000_write=any(f['bytes']==[0x90,8,0x7d,0] and
                    all(f['ack']) and f['end']=='stop' for f in frames),
                matched_enable_write=any(f['bytes']==[0x90,3,2,0] and
                    all(f['ack']) and f['end']=='stop' for f in frames))


def read_channel(scope, channel, count):
    scope.write(f':WAVeform:SOURce CHANnel{channel}')
    scope.write(':WAVeform:MODE RAW')
    scope.write(':WAVeform:FORMat BYTE')
    pre = [float(v) for v in scope.ask(':WAVeform:PREamble?').split(',')]
    chunks = []
    for start in range(1, count+1, 200000):
        stop = min(start+199999, count)
        scope.write(f':WAVeform:STARt {start}')
        scope.write(f':WAVeform:STOP {stop}')
        block = scope.ask_raw(b':WAVeform:DATA?')
        if block[:1] != b'#':
            raise RuntimeError('Expected IEEE binary block')
        digits = int(block[1:2])
        size = int(block[2:2+digits])
        data = block[2+digits:2+digits+size]
        if size != stop-start+1 or len(data) != size:
            raise RuntimeError('Incomplete waveform block')
        chunks.append(np.frombuffer(data, dtype=np.uint8).copy())
    raw = np.concatenate(chunks)
    return raw, pre, (raw.astype(float)-pre[8]-pre[9])*pre[7]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--probes-confirmed', action='store_true', required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--scl-channel',type=int,choices=range(1,5),default=2)
    ap.add_argument('--sda-channel',type=int,choices=range(1,5),default=4)
    args = ap.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    if args.scl_channel==args.sda_channel:
        ap.error('SCL and SDA require different scope channels')
    channels=(args.scl_channel,args.sda_channel)
    report = dict(events=[], completed=False, physical_connection={
        'SCL':args.scl_channel,'SDA':args.sda_channel,'probe_attenuation':10,'VOUT':None})
    agent = SerialAgent('COM7', os.environ['PYNQ_SSH_PASSWORD'], report['events'])
    scope = None
    closed = False
    try:
        scope = Scope()
        report['connected'] = agent.connect()
        report['initialized'] = agent.call('initialize', timeout=120)
        assert all(not o['enabled'] for o in report['initialized']['outputs'])
        scope.write(':STOP')
        for ch in (1,2,3,4):
            scope.write(f':CHANnel{ch}:DISPlay '+('ON' if ch in channels else 'OFF'))
        for ch in channels:
            for setting,value in [('PROBe',10),('COUPling','DC'),
                                  ('INVert','OFF'),('BWLimit','OFF'),
                                  ('SCALe',1),('OFFSet',-1.5)]:
                scope.write(f':CHANnel{ch}:{setting} {value}')
        for command in (':TIMebase:MODE MAIN', ':TIMebase:MAIN:SCALe 0.1',
                        ':TIMebase:MAIN:OFFSet 0', ':ACQuire:TYPE NORM',
                        ':TRIGger:MODE EDGE', f':TRIGger:EDGe:SOURce CHAN{args.sda_channel}',
                        ':TRIGger:EDGe:SLOPe NEG', ':TRIGger:EDGe:LEVel 1.5',
                        ':TRIGger:SWEep AUTO', ':RUN', ':ACQuire:MDEPth 600000'):
            scope.write(command)
        depth = int(float(scope.ask(':ACQuire:MDEPth?')))
        if depth != 600000:
            raise RuntimeError(f'Unexpected capture depth: {depth}')
        time.sleep(.7)
        report['idle_voltage_v']={str(ch):float(scope.ask(f':MEASure:ITEM? VAVG,CHANnel{ch}')) for ch in channels}
        if any(not 1.8 < v < 4.5 for v in report['idle_voltage_v'].values()):
            raise RuntimeError('Idle bus voltage inconsistent with two x10 probes on SCL/SDA; check wiring/attenuation')
        scope.write(':SINGle')
        time.sleep(.2)
        if scope.ask(':TRIGger:STATus?') == 'STOP':
            raise RuntimeError('Scope triggered before the requested transaction')
        report['output'] = agent.call('output', dict(channel=0,action='start',
            mode='dc_code',offset=2000,wiring_confirmed=True))
        deadline = time.monotonic()+5
        while scope.ask(':TRIGger:STATus?') != 'STOP':
            if time.monotonic() >= deadline:
                raise TimeoutError('No completed SCL/SDA capture')
            time.sleep(.1)
        report['cleanup'] = agent.close()
        closed = True
        print('TX1_OUTPUTS_CLOSED', json.dumps(report['cleanup']), flush=True)
        records = {ch:read_channel(scope,ch,depth) for ch in channels}
        if records[channels[0]][1][4:7] != records[channels[1]][1][4:7]:
            raise RuntimeError('Scope channel time axes differ')
        raw_file = args.report.with_suffix('.npz')
        np.savez_compressed(raw_file, **{f'{key}{ch}':records[ch][i]
            for ch in records for key,i in [('raw',0),('preamble',1)]})
        report['raw_file'] = str(raw_file.resolve())
        report['decoded'] = decode_i2c(records[channels[0]][2], records[channels[1]][2], records[channels[0]][1][4])
        report['voltage_percentiles'] = {str(ch):np.percentile(records[ch][2],[1,50,99]).tolist() for ch in records}
        report['completed'] = True
        print('TX1_BUS_DECODE', json.dumps(report['decoded']), flush=True)
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        if not closed:
            try: report['cleanup'] = agent.close()
            except Exception as error: report['cleanup_error'] = repr(error)
        if scope is not None:
            try: scope.write(':STOP'); scope.s.close()
            except Exception as error: report['scope_close_error'] = repr(error)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
