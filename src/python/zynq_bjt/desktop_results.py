"""Display saved measurements without recalculating them using current settings."""
import csv
import json
import math
from pathlib import Path

TABLE_COLUMNS = (
    ('n','序号',65), ('x','X',105), ('y','Y',105), ('beta','β = IC / IB',110),
    ('ve','VE 换算 / V',110), ('extra','数据来源',100),
    ('curve','曲线 / 档位',120), ('condition','曲线条件',180), ('point','曲线内点号',100),
    ('rx1_code','RX1 均值 / 码',130), ('rx2_code','RX2 均值 / 码',130),
    ('rx1_v','ADC2 / RX1 实采 / V',170), ('rx2_v','ADC1 / RX2 实采 / V',170),
    ('vb','VB 换算 / V',120), ('vc','VC 换算 / V',120), ('vcc','VCC 反馈 / V',120),
    ('predicted','功放端口预计 VCC / V',185), ('tx1','TX1 设定 / V',120), ('tx2','TX2 设定 / V',120),
    ('vin_peak','Vin 预计峰值 / V',150), ('vb_peak','VB 换算峰值 / V',150), ('out_peak','输出换算峰值 / V',160),
    ('sample_uce','ADC 对应实采 UCE / V',180), ('adc_basis','ADC / 结果对应关系',240),
    ('base_r','IB 换算等效电阻 / Ω',180),('rin','输入电阻估算 / Ω',160))


def number(value, scale=1):
    try:
        value=float(value)*scale
        return '{:.7g}'.format(value) if math.isfinite(value) else '—'
    except (ValueError, TypeError): return '—'


def point_details(row, measurement, profile):
    curve=int(float(row.get('curve') or 0))
    condition = ('VCC' if profile.pnp else 'UCE')+' = '+number(row.get('vcc_v') if profile.pnp else row.get('uce_target_v'))+' V'
    if measurement in ('output','beta'):
        condition='IB ≈ '+number(row.get('ib_estimated_a'),1e3 if profile.big else 1e6)+(' mA' if profile.big else ' μA')
    if measurement=='beta': condition+='；'+('插值' if row.get('pick_method')=='interpolated' else '最近实测点')
    group='曲线 {}'.format(curve+1) if measurement!='beta' else '基极档 {}'.format(curve+1)
    if measurement=='ac':
        group='二分补测' if row.get('mode')=='refine' else '顺序扫描'
        condition='TX1 = '+number(row.get('tx1_bias_v'))+' V'
    basis = '当前测点实采'
    if measurement=='beta':
        basis=('β 插值；ADC 为邻近实采点' if row.get('pick_method')=='interpolated' else '最近实采点') if row.get('adc_basis') else '旧记录未保存 ADC 对应关系'
    return dict(curve=group,condition=condition,point=number(float(row['index'])+1) if row.get('index') not in (None,'') else '—',
                rx1_code=number(row.get('rx1_rms_code' if measurement=='ac' else 'rx1_mean_code')),
                rx2_code=number(row.get('rx2_rms_code' if measurement=='ac' else 'rx2_mean_code')),
                rx1_v=number(row.get('rx1_port_ac_rms_v' if measurement=='ac' else 'rx1_port_v')),
                rx2_v=number(row.get('rx2_port_ac_rms_v' if measurement=='ac' else 'rx2_port_v')),
                vb=number(row.get('vb_v')),vc=number(row.get('vc_v')),ve=number(row.get('ve_v')),
                vcc=number(row.get('vcc_v')),predicted=number(row.get('vcc_predicted_v')),
                tx1=number(row.get('tx1_request_v',row.get('tx1_v',row.get('tx1_bias_v')))),
                tx2=number(row.get('tx2_request_v',row.get('tx2_vcc_control_v'))),
                vin_peak=number(row.get('source_node_v_peak')),vb_peak=number(row.get('input_node_v_peak')),
                out_peak=number(row.get('output_node_v_peak')),sample_uce=number(row.get('sample_uce_v')),adc_basis=basis,
                base_r=number(row.get('base_resistance_ohm')),rin=number(row.get('input_resistance_ohm')))


def latest_result(root, measurement, profile, measurements, method=None):
    """Find the latest matching nonempty local run, including partial runs."""
    from .result_paths import run_method
    candidates=[]
    for path in Path(root).rglob('run.json'):
        try:
            state=json.loads(path.read_text(encoding='utf-8-sig'))
            name=state.get('measurement')
            if name is None and 'uce_values_v' in state.get('config',{}): name='input'
            key=state.get('profile',state.get('config',{}).get('profile','npn_small'))
            if name!=measurement or key!=profile:continue
            if method is not None and run_method(state)!=method:continue
            csv_path=path.parent/measurements[measurement][2]
            with csv_path.open(encoding='utf-8-sig',newline='') as stream:
                if next(csv.DictReader(stream),None) is None:continue
            stamp=float(state.get('finished_at') or state.get('started_at') or path.stat().st_mtime)
            if not math.isfinite(stamp):continue
            candidates.append((stamp,path.parent.name,dict(state=state,run_id=path.parent.name,
                directory=str(path.parent),local_directory=str(path.parent))))
        except (OSError,ValueError,TypeError,KeyError):continue
    return max(candidates,key=lambda item:item[:2])[2] if candidates else None
