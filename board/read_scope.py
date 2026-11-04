"""Read Rigol CH settings, DC measurements and PNG without changing acquisition."""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'build/tool_deps/instruments'))
try:
    import xdrlib
except ImportError:
    import xdrlib3
    sys.modules['xdrlib'] = xdrlib3
import vxi11


def read_scope(ip, channel, prefix, connection, scope=None):
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    result = {'at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
              'ip': ip, 'channel': channel, 'connection': connection,
              'acquisition_changed': False, 'queries': {}}
    owned = scope is None
    if owned:
        with socket.create_connection((ip, 111), timeout=3) as probe:
            result['local_address'] = probe.getsockname()[0]
        scope = vxi11.Instrument(ip)
        scope.timeout = 5
    def query(command):
        value = scope.ask(command).strip()
        result['queries'][command] = value
        return value
    try:
        result['idn'] = query('*IDN?')
        if 'RIGOL' not in result['idn'] or 'DS1104Z' not in result['idn']:
            raise RuntimeError('Unexpected instrument: '+result['idn'])
        for q in (':TRIGger:STATus?', ':TIMebase:SCALe?', ':ACQuire:TYPE?', ':ACQuire:SRATe?'):
            query(q)
        for name in ('DISPlay', 'COUPling', 'PROBe', 'SCALe', 'OFFSet', 'INVert', 'BWLimit', 'UNITs'):
            query(':CHANnel{}:{}?'.format(channel, name))
        for name in ('VAVG', 'VMAX', 'VMIN', 'VPP', 'VRMS'):
            query(':MEASure:ITEM? {},CHANnel{}'.format(name, channel))
        raw = scope.ask_raw(b':DISPlay:DATA? ON,OFF,PNG')
        if not raw.startswith(b'#') or raw[1:2] not in b'123456789':
            raise ValueError('Unexpected screenshot header')
        n = int(raw[1:2]); length = int(raw[2:2+n])
        png = raw[2+n:2+n+length]
        if len(png) != length or not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Incomplete screenshot')
        prefix.with_suffix('.png').write_bytes(png)
        result['screenshot'] = str(prefix.with_suffix('.png').resolve())
        result['read_completed'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        if owned:
            try: scope.close()
            except Exception as error: result['scope_close_error'] = repr(error)
        prefix.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', default='169.254.1.5')
    parser.add_argument('--channel', type=int, choices=range(1,5), default=3)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--connection', default='User confirmed CH3 on ADDA TX2 connector; output state not independently verified')
    args = parser.parse_args()
    print(json.dumps(read_scope(args.ip,args.channel,args.prefix,args.connection),ensure_ascii=False,indent=2))
