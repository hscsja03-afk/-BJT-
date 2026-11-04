"""Stable, portable result folders; legacy flat records remain readable."""
from pathlib import Path, PurePosixPath
import time
import uuid

PROFILES = {'npn_small':'NPN小功率', 'npn_big':'NPN大功率',
            'pnp_small':'PNP小功率', 'pnp_big':'PNP大功率', 'instrument':'仪器'}
MEASUREMENTS = {'input':'输入特性', 'output':'输出特性', 'beta':'线性精度',
                'ac':'交流特性', 'detect':'极性识别', 'scope':'示波器', 'meter':'万用表'}


METHODS = {'step':'步进', 'pulse':'脉冲'}


def supports_pulse(profile, measurement):
    return profile in ('npn_big','pnp_big') and measurement in ('output','beta')


def run_method(state):
    return state.get('method') or ('pulse' if state.get('config',{}).get('scan_mode')=='脉冲' else 'step')


def group(profile, measurement, method='step'):
    if method not in METHODS:raise ValueError('未知扫描方式')
    path=Path(PROFILES[profile]) / MEASUREMENTS[measurement]
    return path / METHODS[method] if supports_pulse(profile,measurement) else path


def create_run(root, profile, measurement, method='step'):
    directory = Path(root) / group(profile, measurement, method) / (time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def relative_run(value):
    """Validate both remote POSIX paths and local Windows-safe components."""
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or str(path)!=value or len(path.parts) not in (1,3,4)
            or any(p in ('.','..') or any(c in p for c in '\\:*?"<>|') or p.endswith((' ','.')) for p in path.parts)):
        raise ValueError('无效记录目录')
    if len(path.parts)>=3 and (path.parts[0] not in PROFILES.values() or path.parts[1] not in MEASUREMENTS.values()):
        raise ValueError('未知记录分类')
    if len(path.parts)==4 and (path.parts[0] not in (PROFILES['npn_big'],PROFILES['pnp_big']) or path.parts[1] not in (MEASUREMENTS['output'],MEASUREMENTS['beta']) or path.parts[2] not in METHODS.values()):
        raise ValueError('未知扫描方式分类')
    return path
