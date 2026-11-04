"""Bundled PDF catalog and manufacturer spelling aliases."""
import json
import re
from pathlib import Path


def vendor_key(value):
    key=re.sub(r'[\s_-]+','',value).casefold()
    if key in ('安森美','安森美半导体','onsemi','onsemiconductor'):return 'onsemi'
    if key in ('长晶','长晶科技','江苏长晶','江苏长晶科技','jscj','changjing'):return 'changjing'
    return key


def find_bundled(data,manufacturer,model):
    root=Path(data)/'datasheets'
    model=re.sub(r'\s+','',model).upper()
    try:catalog=json.loads((root/'sources.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return None
    for item in catalog:
        if vendor_key(item['manufacturer'])==vendor_key(manufacturer) and item['model'].upper()==model:
            path=root/item['file']
            if path.is_file():return path
    return None
