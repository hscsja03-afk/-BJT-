"""User-confirmed 2026-10-30 fixture routing and explicitly provisional transfers.

Pair strings follow the user's pin order, not AXI bit order: (77,48),
(79,81), (83,85). GPIO bits are X1.(87,85,83,81,79,77,48).
"""
from dataclasses import dataclass
import math

PIN_BY_BIT = (87, 85, 83, 81, 79, 77, 48)
LABELS = {'npn_small': 'NPN 小功率', 'npn_big': 'NPN 大功率',
          'pnp_small': 'PNP 小功率', 'pnp_big': 'PNP 大功率'}
RANGES = {'input': ((0, 1), 200000.0, 100e-9, 10e-6),
          'small_output': ((0, 0), 2000.0, 10e-6, .001),
          'big_output': ((1, 0), 50.0, .0004, .04)}


@dataclass(frozen=True)
class Profile:
    key: str = 'npn_small'

    def __post_init__(self):
        if self.key not in LABELS: raise ValueError('Unknown BJT profile: '+str(self.key))

    @property
    def pnp(self): return self.key.startswith('pnp_')
    @property
    def big(self): return self.key.endswith('_big')
    @property
    def label(self): return LABELS[self.key]
    @property
    def collector_ohm(self): return 1.0 if self.big else 100.0
    @property
    def voltage_axis(self): return 'UEC' if self.pnp else 'UCE'
    @property
    def input_axis(self): return 'UEB' if self.pnp else 'UBE'

    def current_range(self, measurement):
        if measurement not in ('input','output','beta','ac'): raise ValueError('Unknown measurement')
        if measurement == 'ac': return RANGES['small_output']
        return RANGES['input' if measurement=='input' else ('big_output' if self.big else 'small_output')]

    def base_ohm(self, measurement): return self.current_range(measurement)[1]

    def route(self, measurement):
        current, resistance, low, high = self.current_range(measurement)
        kind = (0, 0) if measurement=='input' else ((0, 1) if measurement=='ac' else (1, 0))
        polarity = int(self.pnp)
        pins = {87:int(self.big), 79:polarity, 81:polarity,
                83:kind[0], 85:kind[1], 77:current[0], 48:current[1]}
        if measurement=='ac':pins[87]=0
        if measurement=='input':pins[87]=0
        value = sum(pins[pin]<<bit for bit,pin in enumerate(PIN_BY_BIT))
        return dict(mask=127, value=value, pin_values=pins,
                    current_range_a=[low,high], base_resistance_ohm=resistance,
                    collector_resistor_ohm=Profile('pnp_small').collector_ohm if measurement=='ac' and self.key=='pnp_big' else self.collector_ohm,
                    pair_order={'current':[77,48], 'polarity':[79,81], 'type':[83,85]},
                    input_pin87_basis='user_confirmed_20261101_all_input_low' if measurement=='input' else None,
                    basis='user_confirmed_20261030',
                    ac_range_basis='user_confirmed_20261102_AC_shared_small_power_range_pin87_low' if measurement=='ac' else 'user_confirmed')

    def output_nodes(self, sense, supply, rc, ib=0.0):
        # PNP: VCC -> sense resistor -> E; C grounded; ADC1 measures VE.
        # User requested IC ~= IE for PNP; retain ib argument for compatibility.
        return sense, (supply-sense)/rc



def validate_profile_config(config, measurement):
    profile = Profile(config.profile)
    for key in ('base_resistance_ohm', 'collector_resistor_ohm'):
        if hasattr(config, key) and (not math.isfinite(getattr(config, key)) or getattr(config, key) <= 0):
            raise ValueError('Current conversion resistances must be finite and positive')
    return profile


def defaults_for(measurement, cls, profile_key='npn_small'):
    from dataclasses import asdict
    from .pulse import default_noise_span_v
    p = Profile(profile_key)
    values = asdict(cls())
    values['profile'] = profile_key
    if 'pulse_noise_span_v' in values:values['pulse_noise_span_v']=default_noise_span_v(profile_key)
    if measurement=='output' and profile_key=='npn_small': values['settle_s']=.05
    if measurement=='input' and p.pnp: values.update(uce_values_v=(1.0,2.0),tx1_stop_v=1.8)
    # Higher-current fixtures retain the existing bias/output envelope until
    # verified on that hardware; increase density without increasing drive.
    if measurement=='beta' and p.big:
        values.update(tx1_stop_v=.08,tx1_step_v=.0025,tx2_stop_v=.28,target_uce_v=1.2,tx2_first_start_v=.24)
    if 'base_resistance_ohm' in values: values['base_resistance_ohm'] = p.base_ohm(measurement)
    if 'collector_resistor_ohm' in values: values['collector_resistor_ohm'] = p.route(measurement)['collector_resistor_ohm']
    return values


def assumptions(profile_key, measurement):
    p = Profile(profile_key)
    return dict(profile=profile_key, route=p.route(measurement),
        confirmed={'input_base_current_tx':2 if p.pnp else 1,'input_bias_amplifier_tx':1 if p.pnp else 2,'input_tx_roles_basis':'user_confirmed_20261101', 'rx2_node':'VE' if p.pnp else 'VC', 'collector_adc_per_v':.206,
                   'rx1_node':'VCC' if measurement in ('output','beta') else ('VB*9.78' if measurement == 'ac' else 'VB/4'),
                   'ac_adc_amplitude_multiplier':1.0, 'ac_half_amplitude_basis':'user_retracted_x2_20261031',
                   'ac_input_adc_per_v':9.78, 'ac_vb_scale_basis':'user_confirmed_20261031',
                   'base_adc_per_v':.25, 'source_adc_per_v':.206, 'vcc_scale_basis':'user_confirmed_20261031',
                   'fixture_adc1':'RX2', 'fixture_adc2':'RX1', 'mapping_basis':'user_corrected_20261031',
                   'tx1_control_range_v':[.02,2.0], 'collector_resistor_ohm':p.route(measurement)['collector_resistor_ohm']},
        provisional={
            'pnp_input_voltage':{'value':'UEB = measured VE - measured VB; VCC controls TX1 through amplifier gain','basis':'user restored ADC1/RX2 VE readout on 20261101'},
            'tx2_power_amplifier_gain':{'value':6.0,'basis':'both reference sources; not remeasured'},
            'pnp_ac_current':{'value':'beta ~= (RB/RE)*VE_peak/(Vin_peak-VB_peak); IC ~= IE = VE_peak/RE','basis':'user circuit: Vin before RB, VB at base, VE at emitter; VCC AC ground; Vin/VB in-phase amplitude approximation; all conversion gains unchanged'},
            'pnp_output_topology':{'value':'C=GND; ADC1=VE; ADC2=VCC; UEC=VE; IC ~= IE = (VCC-VE)/R','basis':'user_confirmed_20261031; user requested IE ~= IC'},
            'ac_input_sample_gain':{'value':1.0,'basis':'AC VB*9.78 is represented by input_adc_per_v=9.78; extra gain stays 1 to avoid applying it twice'},
            'ac_input_resistor_ohm':{'value':50.0,'basis':'IP-SDK small-signal method; shared provisional constant for four profiles'},
            'ac_source_buffer_gain':{'value':0.84,'basis':'User measured TX3 50 mVpp -> buffer output 42 mVpp on 2026-10-31; assumed constant versus frequency/amplitude pending verification'},
            'ac_phase':{'value':'source and base assumed in phase','basis':'legacy magnitude subtraction; no phase measurement'},
            'ac_range':{'value':p.route('ac')['pin_values'],'basis':p.route('ac')['ac_range_basis']},
        }, absolute_measurement_accuracy_verified=False)
