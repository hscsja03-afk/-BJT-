"""Packaged-runtime verification; optional board connection remains read-only."""
from dataclasses import asdict
import csv
import json
import os
from pathlib import Path
import time
from .desktop_session import Session, MEASUREMENTS
from .desktop_transport import SshTransport
from .profiles import LABELS, defaults_for
from .desktop_output import defaults as tx_defaults, prepare as prepare_tx
from .desktop_results import latest_result


def verify(assets, report, host=None):
    report = Path(report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    evidence = {'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'checks': [], 'passed': False}
    session = Session(assets/'data', report.parent/'desktop_simulation_runs', simulated=True)
    transport = None
    try:
        profile=session.cal.tx3_waveforms
        compatibility=[]
        for entry in (profile or {}).get('compatible_bitstreams',[]):
            identity=dict(bit_sha256=entry['bitstream_sha256'],hwh_sha256=entry['hwh_sha256'],
                          dac_divider=1000000000/entry['dac_sample_rate_hz'])
            plan=session.cal.bind_waveform_plan(session.cal.sine_parameters(100000,.05),identity)
            assert plan['amplitude_basis']=='compatible_bitstream_reference_unverified'
            assert plan['bitstream_reference']['analog_recalibrated'] is False
            for bad in ({'bit_sha256':'unknown'},{'hwh_sha256':'unknown'},{'dac_divider':20}):
                try:session.cal.validate_waveform_identity(dict(identity,**bad))
                except ValueError:pass
                else:raise AssertionError('TX3 mismatch was accepted')
            compatibility.append(plan['bitstream_reference'])
        evidence['tx3_bitstream_compatibility']=compatibility
        gpio_only = session.gpio(dict(mask=127, value=0x55))
        assert not gpio_only['initialized'] and gpio_only['gpio']['output'] == 0x55
        assert session.stop()['gpio']['output'] == 0
        session.initialize()
        tx2_library=session.cal.tx2_waveform_library
        evidence['tx2_verified_subsets']=[]
        if tx2_library:
            for profile in [tx2_library]+tx2_library.get('hardware_variants',[]):
                identity=dict(bit_sha256=profile['bitstream_sha256'],hwh_sha256=profile['hwh_sha256'],dac_divider=8)
                session.cal.select_tx2_waveform_profile(identity)
                session.cal.validate_tx2_waveform_identity(identity)
                for point in profile['points']:
                    prepared=prepare_tx(1,point['shape'],'voltage',dict(offset=profile['offset_v'],
                        peak=point['target_vpp_v']/2,frequency_hz=point['frequency_hz'],phase_degrees=0,duty_percent=50),
                        session.cal,confirmed=True)
                    request=prepared['request']
                    assert request['tx2_waveform_calibration_id']==profile['calibration_id']
                    assert request['offset']==point['zero_code'] and request['peak']==point['peak_codes']
                    status=session.output(request)
                    assert status['output_settings']['1']['tx2_waveform_calibration_id']==profile['calibration_id']
                evidence['tx2_verified_subsets'].append(dict(calibration_id=profile['calibration_id'],nodes=len(profile['points']),simulated=True))
            session.cal.select_tx2_waveform_profile()
        evidence['tx3_exact_override_nodes']=0
        for point in (session.cal.tx3_waveforms or {}).get('exact_overrides',{}).get('points',[]):
            prepared=prepare_tx(2,point['shape'],'voltage',dict(offset=0,
                peak=point['target_vpp_v']/2,frequency_hz=point['frequency_hz'],phase_degrees=0,duty_percent=50),
                session.cal,confirmed=True)
            request=prepared['request']
            assert request['offset']==point['zero_code'] and request['peak']==point['peak_codes']
            status=session.output(request)
            assert status['output_settings']['2']['waveform_calibration_id']==session.cal.tx3_waveforms['calibration_id']
            evidence['tx3_exact_override_nodes']+=1
        from .scope_display import spectrum
        import math
        fft=spectrum([math.sqrt(2)*math.sin(2*math.pi*32*i/1024) for i in range(1024)],102400)
        assert abs(float(fft['rms'][32])-1)<1e-10
        assert float(fft['frequency_hz'][32])==3200
        evidence['scope_fft']=dict(passed=True,bins=len(fft['rms']),unit='RMS',peak_hz=3200)
        frame=session.capture(dict(sample_count=4096,sample_stride=64))
        assert len(frame['words'][0])==4096 and frame['sample_rates_hz'][0]==50e6/64
        evidence['adjustable_capture']=dict(passed=True,points=4096,stride=64,simulated=True)
        fft=spectrum([1 if ((i*71.4/4096)%1)<.5 else -1 for i in range(4096)],1e6,'flattop')
        assert abs(fft['peak_rms']-2*math.sqrt(2)/math.pi)<.005 and abs(fft['ac_rms']-1)<.005
        evidence['square_fft']=dict(passed=True,peak_rms=fft['peak_rms'],ac_rms=fft['ac_rms'])
        for channel in range(3):
            before = session.output(dict(channel=channel, mode='dc_code', offset=100+channel,
                                         action='start', wiring_confirmed=True))
        after = session.gpio(dict(mask=127, value=61))
        assert after['outputs'] == before['outputs'] and after['output_settings'] == before['output_settings']
        stopped = session.stop()
        assert stopped['gpio']['output'] == 0 and stopped['gpio']['sense'] == 0
        assert not any(o['enabled'] for o in stopped['outputs'])
        evidence['gpio_dac_independence'] = dict(gpio_only=gpio_only, before=before, after=after, stopped=stopped)
        evidence['voltmeter'] = session.dispatch('meter')
        assert all(abs(row['dc_v']-.3)<1e-8 and abs(row['ac_rms_v']-.1/2**.5)<1e-8
                   for row in evidence['voltmeter']['channels'])
        assert not any(session.board.enabled)
        evidence['tx_controls'] = []
        for channel in range(3):
            for wave in (('dc',) if channel == 0 else ('dc','sine','square','triangle')):
                for unit in ('voltage','code'):
                    plan = prepare_tx(channel, wave, unit, tx_defaults(channel,wave,unit,session.cal),
                                      session.cal, confirmed=True, action='start')
                    status = session.output(plan['request'])
                    assert status['outputs'][channel]['enabled']
                    session.output(dict(channel=channel, action='stop'))
                    evidence['tx_controls'].append(dict(channel=channel,wave=wave,unit=unit,
                        request_mode=plan['request']['mode'],preview_min=min(plan['preview']),
                        preview_max=max(plan['preview']),simulated=True))
        evidence['tx3_extended_amplitude'] = []
        for frequency in (100000,3000000):
            for peak in (.03,.05,.1,.5,1.):
                values=dict(tx_defaults(2,'sine','voltage',session.cal),peak=peak,frequency_hz=frequency)
                plan=prepare_tx(2,'sine','voltage',values,session.cal,confirmed=True,action='start')
                status=session.output(plan['request'])
                assert status['outputs'][2]['enabled']
                assert status['output_settings']['2']['sine_amplitude_basis']==session.cal.sine_parameters(frequency,2*peak)['amplitude_basis']
                session.output(dict(channel=2,action='stop'))
                evidence['tx3_extended_amplitude'].append(dict(peak_v=peak,frequency_hz=frequency,simulated=True))
        for profile in LABELS:
            for name, (cls, _, file) in MEASUREMENTS.items():
                config = defaults_for(name, cls, profile); config['settle_s'] = 0
                if name == 'input': config.update(tx1_stop_v=.06, uce_values_v=(1,2), curve_settle_s=0, frame_gap_s=0)
                if name == 'ac': config.update(repeat_count=2, max_bisection_iterations=2)
                if name=='output' and profile=='pnp_big':config['base_control_v']=(.05,.15,.5)
                session.board.gpio(127, 0x55)
                for channel in range(3): session.board.enable(channel, True)
                result = session.scan(dict(measurement=name, profile=profile, config=config, prepare_outputs=True))
                assert result['state']['status'] == 'complete', result['state'].get('error')
                assert not any(output['enabled'] for output in result['state']['initial_outputs'])
                assert result['state']['simulated'] is True
                assert session.board.gpio_value == 0x55 and not any(session.board.enabled)
                with (Path(result['directory'])/file).open(encoding='utf-8-sig', newline='') as stream:
                    rows = list(csv.DictReader(stream))
                assert rows and all(row['simulated'] == '1' and row['profile']==profile for row in rows)
                detail_fields={'input':('rx1_mean_code','rx2_mean_code','rx1_port_v','rx2_port_v','vcc_predicted_v'),
                    'output':('rx1_mean_code','rx2_mean_code','rx1_port_v','rx2_port_v','vcc_predicted_v'),
                    'beta':('rx1_mean_code','rx2_mean_code','rx1_port_v','rx2_port_v','sample_uce_v','adc_basis'),
                    'ac':('rx1_rms_code','rx2_rms_code','rx1_port_ac_rms_v','rx2_port_ac_rms_v','input_node_v_peak','output_node_v_peak')}[name]
                assert all(row.get(key) not in (None,'') for row in rows for key in detail_fields)
                restored=latest_result(session.results,name,profile,MEASUREMENTS)
                assert restored and restored['run_id']==result['run_id']
                if profile=='npn_big' and name=='ac':assert result['state']['source_parameters']['gpio_value']==2
                if name=='input':
                    assert result['state']['measurement_gpio']['pin_values'][87]==0
                    if profile.startswith('pnp'):
                        assert result['state']['ve_feedback_conversion']['points']==session.cal.ve_feedback['points']
                        assert all(row['ve_conversion_basis'].startswith('scope_table_') for row in rows)
                        assert all(abs(float(row['ve_v'])-session.cal.ve_from_port(float(row['rx2_port_v']),profile))<1e-9 for row in rows)
                if name in ('output','beta'):
                    assert all(float(row['base_resistance_ohm'])==config['base_resistance_ohm'] for row in rows)
                    voltage_key='tx1_table_v' if name=='output' else 'tx1_v'
                    assert all(abs(float(row['ib_estimated_a'])-float(row[voltage_key])/config['base_resistance_ohm'])<1e-12 for row in rows)
                if profile=='pnp_big' and name=='output':
                    point=next(row for row in rows if float(row['tx1_request_v'])==.5)
                    assert abs(float(point['ib_estimated_a'])-.01)<1e-5
                    evidence['pnp_big_half_volt_ib']=dict(control_v=.5,resistance_ohm=50,ib_a=float(point['ib_estimated_a']))
                evidence['checks'].append({'measurement': name, 'profile':profile, 'rows': len(rows), 'directory': result['directory'], 'simulated': True,
                                          'point_detail_fields':detail_fields,'latest_result_restored':True,
                                          'all_three_outputs_active_before_preparation': True, 'automatic_output_preparation_passed': True})
        evidence['polarity_detection'] = []
        for profile,rc in (('npn_small',100),('npn_big',1)):
            for device in ('npn','pnp','open','ambiguous'):
                result=session.detect(dict(config=dict(profile=profile,collector_resistor_ohm=rc,settle_s=0),simulated_device=device))
                state=result['state'];assert state['status']=='complete',state
                assert state['classification']['polarity']==(device if device in ('npn','pnp') else 'unknown')
                assert state['points']==8 and not state['cleanup_errors']
                assert not any(session.board.enabled) and session.board.gpio()['output']==0
                evidence['polarity_detection'].append(dict(profile=profile,device=device,classification=state['classification']))
        import pymupdf
        document=pymupdf.open();document.new_page().insert_text((30,30),'Packaged PDF verification')
        pdf_path=report.parent/'pdf_verification.pdf';document.save(pdf_path);document.close()
        with pymupdf.open(pdf_path) as document:
            pix=document[0].get_pixmap(alpha=False)
            assert pix.width>0 and len(pix.samples)>0
        evidence['pdf_rendering']=True
        import tkinter as tk
        from .pdf_view import PdfPane
        pdf_root=tk.Tk();pdf_root.withdraw()
        pdf_view=PdfPane(pdf_root)
        try:
            with pymupdf.open() as test_pdf:
                for _ in range(3):test_pdf.new_page()
                pdf_view.set_document(test_pdf);pdf_view.goto_page(1)
                assert len(pdf_view.pages)==3 and pdf_view.position()[0]==1
                assert pdf_view.photo is not None
                evidence['continuous_pdf']=dict(pages=3,centered=True,passed=True)
                pdf_view.clear()
        finally:pdf_root.destroy()
        from .datasheets import find_bundled
        import hashlib
        evidence['original_project_datasheets']=[]
        for item in json.loads((assets/'data/datasheets/sources.json').read_text(encoding='utf-8')):
            path=find_bundled(assets/'data',item['manufacturer'],item['model'])
            assert path and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
            with pymupdf.open(path) as pdf:
                pix=pdf[0].get_pixmap(matrix=pymupdf.Matrix(.5,.5),alpha=False)
                assert pix.width>0 and len(pix.samples)>0
                evidence['original_project_datasheets'].append(dict(manufacturer=item['manufacturer'],model=item['model'],pages=len(pdf),source_archive=item['source_archive']))
        assert len(evidence['original_project_datasheets'])==8
        from .datasheet_extract import extract_isolated
        result,target=extract_isolated(find_bundled(assets/'data','长晶科技','2N5401'),report.parent/'extraction_verify')
        assert len(result['parameters'])==18
        assert result['reviewed_parameter_count']==18 and not result['review_required']
        assert all(row.get('extracted_candidate') and row.get('review_evidence') for row in result['parameters'])
        from .datasheet_extract import FIELDS
        assert not any(c in row[field] for row in result['parameters'] for field in FIELDS for c in '芯查')
        assert any(row['value']=='-150' for row in result['parameters'])
        evidence['datasheet_extraction']=dict(passed=True,parameters=len(result['parameters']),reviewed=18,watermark_removed=True,cache=str(target),isolated=True)
        from .ai_client import Client, result_context
        import threading
        client=Client(dict(url='https://api.openai.com/v1'),threading.Event())
        assert result_context(dict(profile='npn_small'),[])['total_rows']==0
        evidence['ai_client_imported_no_external_request']=True
        if host:
            transport = SshTransport()
            before = transport.connect(host, 'xilinx', os.environ['PYNQ_SSH_PASSWORD'],
                report.parent/'desktop_known_hosts', assets/'data', (assets/'agent.pyz').read_bytes())
            assert before['initialized'] is False
            try: transport.call('scan', {'measurement': 'input'})
            except RuntimeError as error: evidence['no_init_scan_rejected'] = str(error)
            else: raise AssertionError('No-init scan must be rejected')
            after = transport.call('status')
            for key in ('registers', 'control', 'dac_mode', 'identity'): assert before[key] == after[key]
            evidence['board'] = {'before': before, 'after': after, 'analog_outputs_enabled': False}
            evidence['board_cleanup'] = transport.close()
        from .ac_history import HistoryLibrary
        history=HistoryLibrary(assets/'data',report.parent/'history_verify_cursor.json')
        assert len(history.records)==46
        import hashlib
        for record in history.records:
            assert hashlib.sha256((history.data/record['id']/'curves.csv').read_bytes()).hexdigest()==record['source_sha256']
        evidence['pnp_history']=dict(records=len(history.records),identified=sum(r['identity_confirmed'] for r in history.records),passed=True)
        evidence['pulse_scans']=[]
        for name,cfg in [('output',dict(base_control_v=(.02,),tx2_control_stop_v=.2,tx2_control_step_v=.1)),
                         ('beta',dict(tx1_start_v=.02,tx1_stop_v=.04,tx1_step_v=.01,drop_initial_points=0,moving_average_window=1))]:
            if name=='output':cfg.update(pulse_frequency_hz=5,pulse_duty_percent=30)
            for pulse_profile in ('npn_big','pnp_big'):
                result=session.scan(dict(measurement=name,profile=pulse_profile,method='pulse',config=dict(cfg,frames_per_point=2,settle_s=0),allow_reference=True))
                assert result['state']['status']=='complete',result['state'].get('error')
                assert not any(session.board.enabled)
                assert result['state']['pulse_actual']['requested_frequency_hz']==cfg.get('pulse_frequency_hz',10)
                assert result['state']['pulse_actual']['requested_duty_percent']==cfg.get('pulse_duty_percent',20)
                evidence['pulse_scans'].append(dict(measurement=name,profile=pulse_profile,simulated=True,points=result['state']['points'],method=result['state']['method'],cleanup_errors=result['state']['cleanup_errors']))
        evidence['simulation_cleanup'] = session.close()
        evidence['passed'] = True
    except BaseException as error:
        import traceback
        evidence['error'] = '{}: {}'.format(type(error).__name__,error)
        evidence['traceback'] = traceback.format_exc()
        raise
    finally:
        session.close()
        if transport is not None: transport.abort()
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')

