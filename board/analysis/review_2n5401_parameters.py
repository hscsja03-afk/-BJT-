"""Record the fields visually checked against this exact PDF's pages 1 and 2."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
digest='39ea698c1449d4c9fcf719a0b7aec4d733e4973f81f900fea50f04c47de60b60'
source=json.loads((ROOT/'report/ui_early_rin_20261102/cleaned_2n5401.json').read_text(encoding='utf8'))
rows=[]
rating_symbols=['VCBO','VCEO','VEBO','IC','PC','R ΚJA','TJ, Tstg']
for i,row in enumerate(source['parameters'][:7]):
    fields=dict(symbol=rating_symbols[i],conditions='Ta=25 °C，除非另有说明',unit=['V','V','V','A','mW','°C/W','°C'][i])
    rows.append(dict(page=row['page'],table=row['table'],row=row['row'],expected_limits={k:row[k] for k in ('min','typ','max','value')},fields=fields))
symbols=['V(BR)CBO','V(BR)CEO','V(BR)EBO','ICBO','IEBO','hFE(1)','hFE(2)','hFE(3)','VCE(sat)','VBE(sat)','fT']
conditions=['IC=-0.1 mA, IE=0','IC=-1 mA, IB=0','IE=-0.01 mA, IC=0','VCB=-120 V, IE=0','VEB=-3 V, IC=0',
            'VCE=-5 V, IC=-1 mA','VCE=-5 V, IC=-10 mA','VCE=-5 V, IC=-50 mA','IC=-50 mA, IB=-5 mA','IC=-50 mA, IB=-5 mA','VCE=-5 V, IC=-10 mA, f=30 MHz']
units=['V','V','V','nA','nA','','','','V','V','MHz']
for i,row in enumerate(source['parameters'][7:]):
    rows.append(dict(page=row['page'],table=row['table'],row=row['row'],expected_limits={k:row[k] for k in ('min','typ','max','value')},
                     fields=dict(symbol=symbols[i],conditions=conditions[i],unit=units[i])))
out=ROOT/'data/datasheets/parameter_reviews';out.mkdir(exist_ok=True)
(out/(digest+'.json')).write_text(json.dumps(dict(source_sha256=digest,reviewed_at='2026-11-02',
    evidence='Original PDF pages 1 and 2 rendered and visually inspected; original numerical min/max/rating columns unchanged',rows=rows),ensure_ascii=False,indent=2),encoding='utf8')
