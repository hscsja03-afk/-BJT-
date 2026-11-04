"""Per-device/per-measurement defaults stored with workspace measurements."""
import json
from dataclasses import asdict
from .profiles import defaults_for


def load_defaults(path,profile,measurements):
    try:saved=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):saved={}
    result={}
    for name,(cls,*_) in measurements.items():
        value=defaults_for(name,cls,profile)
        if profile=='pnp_big' and name=='ac':
            small=saved.get('pnp_small',{}).get('ac',{})
            for field in ('base_resistance_ohm','collector_resistor_ohm'):
                if field in small:value[field]=small[field]
        custom=saved.get(profile,{}).get(name,{})
        value.update({k:v for k,v in custom.items() if k in value and k!='profile'})
        for k,v in asdict(cls()).items():
            if isinstance(v,tuple):value[k]=tuple(value[k])
        result[name]=value
    return result


def save_default(path,profile,measurement,config):
    try:saved=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):saved={}
    saved.setdefault(profile,{})[measurement]=config
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(saved,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(path)
