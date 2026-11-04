"""Desktop responsiveness/storage regressions; use the desktop Python environment."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.desktop_storage import workspace_path


class StorageTests(unittest.TestCase):
    def test_launch_location_independent_and_portable(self):
        self.assertEqual(workspace_path(executable=ROOT/'build/dist/desktop/ZynqBjtDesktop/app.exe'), ROOT/'measurements')
        directory = Path(ROOT.anchor)/'portable_bjt_test'
        self.assertEqual(workspace_path(executable=directory/'app.exe'), directory/'measurements')
        self.assertEqual(workspace_path(directory/'custom'), directory/'custom')

    def test_migration_preserves_both_versions_and_rechecks_hashes(self):
        spec = importlib.util.spec_from_file_location('migration', ROOT/'board/analysis/migrate_desktop_data.py')
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            source, target = Path(temp)/'old', Path(temp)/'new'
            source.mkdir(); target.mkdir()
            (source/'data.csv').write_text('legacy data')
            (target/'data.csv').write_text('new measurement')
            (source/'known_hosts').write_text('test host key')
            report = migration.migrate(source, target)
            self.assertTrue(report['verified'])
            self.assertEqual((target/'data.csv').read_text(), 'new measurement')
            self.assertEqual((source/'data.csv').read_text(), 'legacy data')
            conflict = next(f for f in report['files'] if f['conflict_preserved'])
            self.assertEqual((target/conflict['destination']).read_text(), 'legacy data')
            self.assertEqual((target/'known_hosts').read_text(), 'test host key')


class UiTests(unittest.TestCase):
    def test_read_result_saves_acquired_curves_and_resistance(self):
        import csv,json
        app=self.app
        cases=[('input',[dict(curve=0,ube_v=.9,ib_estimated_a=12e-6,uce_target_v=.5)],['curve.png']),
               ('beta',[dict(curve=i,ib_estimated_a=(i+1)*1e-5,ic_a=(i+1)*.001) for i in range(3)],['curve_ic_ib.png','curve_beta_ic.png','curve_beta_ib.png']),
               ('ac',[dict(actual_freq_hz=10000,gain=23,mode='sweep',input_resistance_ohm=500)],['curve.png'])]
        from zynq_bjt.desktop_session import MEASUREMENTS
        for name,rows,images in cases:
            if name=='ac':
                app.profile.set('PNP 小功率');app.change_profile()
                app.tools.manufacturer.set('长晶科技');app.tools.model.set('2N5401')
            app.show_page(name);app.beta_processing.set('全部原始点')
            directory=Path(self.temp.name)/name;directory.mkdir()
            path=directory/MEASUREMENTS[name][2]
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            before=path.read_bytes()
            app.last_result=dict(state=dict(measurement=name,profile=app.selected_profile().key,simulated=True,status='cancelled',config={}),local_directory=str(directory))
            app.read_result(directory)
            self.assertEqual(path.read_bytes(),before)
            for image in images:
                self.assertGreater((directory/image).stat().st_size,1000)
                metadata=json.loads((directory/image).with_suffix('.source.json').read_text(encoding='utf8'))
                self.assertEqual(metadata['status'],'cancelled')
            if name=='ac':
                self.assertEqual(sorted(p.name for p in directory.glob('*.png')),['curve.png'])
                rin_meta=json.loads((directory/'derived_analysis/input_resistance.source.json').read_text(encoding='utf8'))
                self.assertEqual(rin_meta['source'],'current_run')
                self.assertEqual(rin_meta['source_file'],path.name)
                import hashlib
                self.assertEqual(rin_meta['source_sha256'],hashlib.sha256(before).hexdigest())
                self.assertEqual(list(app._curve_lines['sweep'].get_ydata()),[23])
                rin=next(line for line in app.derived_plots.tabs['ac'][2].lines if line.get_label()=='扫描点')
                self.assertEqual(list(rin.get_ydata()),[500])

    def test_adc_clock_controls_follow_board_limit_and_clear_old_frames(self):
        from types import SimpleNamespace
        app=self.app;scope=app.scope
        app.transport=SimpleNamespace(alive=True)
        app.last_status=dict(initialized=True,adc_max_rate_hz=62500000)
        scope.controls()
        self.assertEqual(tuple(scope.adc_clock_choice.cget('values')),('50','62.5'))
        scope.frame={'old':True};app.last_frame=scope.frame
        scope.history.append({'old':True})
        scope.clock_applied(dict(sample_rates_hz=[62500000.,62500000.]))
        self.assertIsNone(scope.frame);self.assertIsNone(app.last_frame)
        self.assertEqual(len(scope.history),0)
        self.assertTrue(scope.raw);self.assertEqual(scope.adc_clock_mhz.get(),'62.5')
        scope.clock_applied(dict(sample_rates_hz=[50000000.,50000000.]))
        self.assertFalse(scope.raw);self.assertEqual(scope.adc_clock_mhz.get(),'50')
        app.transport=None

    def test_pnp_ac_plots_follow_acquired_gain_and_resistance(self):
        app=self.app
        for label,key in [('PNP 小功率','pnp_small'),('PNP 大功率','pnp_big')]:
            app.profile.set(label);app.change_profile();app.show_page('ac')
            app.last_result=dict(state=dict(measurement='ac',profile=key,simulated=True,status='running',config={}))
            points=[dict(actual_freq_hz=10000,gain=23,input_resistance_ohm=500,mode='sweep'),
                    dict(actual_freq_hz=40000,gain=47,input_resistance_ohm=750,mode='sweep')]
            for count in (1,2):
                app.rows=points[:count];app.plot_rows(app.rows)
                line=app._curve_lines['sweep']
                self.assertEqual(list(line.get_xdata()),[p['actual_freq_hz'] for p in points[:count]])
                self.assertEqual(list(line.get_ydata()),[p['gain'] for p in points[:count]])
                ax=app.derived_plots.tabs['ac'][2]
                rin=next(line for line in ax.lines if line.get_label()=='扫描点')
                self.assertEqual(list(rin.get_ydata()),[p['input_resistance_ohm'] for p in points[:count]])
                app.lcd.model.page='BJT'
                for mode,field in [('交流','gain'),('Rin','input_resistance_ohm')]:
                    app.lcd.model.mode=mode;app.lcd._bjt_current()
                    self.assertEqual(app.lcd.model.saved_plot['curves'][0][0],
                        [(p['actual_freq_hz']/1000,p[field]) for p in points[:count]])
            app.rows=[];app.plot_rows([])
            self.assertEqual(len(app.ax.lines),0)
            self.assertEqual(len(app.derived_plots.tabs['ac'][2].lines),0)


    def test_npn_big_pulse_selector_and_request_match(self):
        app=self.app;app.profile.set('NPN 大功率');app.change_profile();app.show_page('output')
        self.assertEqual(tuple(app.config_entries['scan_mode'].cget('values')),('步进','脉冲'))
        app.config_vars['scan_mode'].set('脉冲');request=app.scan_request()
        self.assertEqual(request['method'],'pulse');self.assertEqual(request['config']['scan_mode'],'脉冲')
        app.show_page('input');self.assertNotIn('scan_mode',app.config_entries)
        app.show_page('beta');app.config_vars['scan_mode'].set('脉冲');self.assertEqual(app.scan_request()['method'],'pulse')
        app.profile.set('PNP 大功率');app.change_profile()
        self.assertEqual(tuple(app.config_entries['scan_mode'].cget('values')),('步进','脉冲'))
        for name in ('output','beta'):
            app.show_page(name);app.config_vars['scan_mode'].set('脉冲')
            request=app.scan_request()
            self.assertEqual(request['method'],'pulse');self.assertEqual(request['profile'],'pnp_big')
        for name in ('input','ac'):
            app.show_page(name);self.assertNotIn('scan_mode',app.config_entries)

    def test_pnp_big_table_method_is_visible_and_linear_ratio_is_not_used(self):
        app=self.app;app.profile.set('PNP 大功率');app.change_profile();app.show_page('input')
        self.assertIn('17 点',app.route_text.get())
        self.assertIn('87=0',app.ve_conversion_text.get())
        self.assertEqual(str(app.frontend_entries['rx1_per_vc'].cget('state')),'disabled')
        app.show_ve_table();self.root.update()
        self.assertEqual(len(app.ve_table_tree.get_children()),17)
        app.ve_table_window.destroy()
        app.config_vars['ve_conversion_mode'].set('线性比例')
        self.assertEqual(str(app.frontend_entries['rx1_per_vc'].cget('state')),'normal')
        app.front_vars['rx1_per_vc'].set('.4')
        self.assertIn('VE×0.4',app.route_text.get())
        app.config_vars['ve_conversion_mode'].set('实测表优先')
        self.assertIn('17 点',app.route_text.get())
    def test_pnp_big_ib_conversion_is_50_ohm_and_npn_custom_values_stay_separate(self):
        app=self.app;app.show_page('output')
        app.profile.set('NPN 大功率');app.change_profile()
        app.config_vars['base_resistance_ohm'].set('100')
        app.profile.set('PNP 大功率');app.change_profile()
        self.assertEqual(app.read_config()['base_resistance_ohm'],50)
        self.assertIn('0.5 V → 10 mA',app.base_conversion_text.get())
        app.config_vars['base_resistance_ohm'].set('100')
        self.assertIn('0.5 V → 5 mA',app.base_conversion_text.get())
        app.reset_base_conversion();app.save_page_default()
        self.assertEqual(app.saved_defaults_for('pnp_big')['output']['base_resistance_ohm'],50)
        app.show_page('beta')
        self.assertIn('0.5 V → 10 mA',app.base_conversion_text.get())
        app.profile.set('NPN 大功率');app.change_profile();app.show_page('output')
        self.assertEqual(app.read_config()['base_resistance_ohm'],100)

    def test_point_columns_add_remove_persist_without_changing_data(self):
        import json
        from types import SimpleNamespace
        app=self.app;app.show_page('output');app.measure_tabs.select(1);self.root.update()
        row=dict(curve=0,index=0,uce_v=1,ic_a=.1,ib_estimated_a=.01,rx1_port_v=.3,base_resistance_ohm=50)
        app.rows=[row];app.append_table_row(row,1)
        stored=app.table.item(app.table.get_children()[0])['values']
        self.assertNotIn('rx1_v',app.table.cget('displaycolumns'))
        app.add_measurement_column('rx1_v')
        self.assertNotIn('rx1_v',app.hidden_measurement_columns())
        self.assertEqual(app.table_selected_column,'rx1_v')
        app.remove_column_button.invoke()
        self.assertIn('rx1_v',app.hidden_measurement_columns())
        self.assertEqual(app.table.item(app.table.get_children()[0])['values'],stored)
        self.assertEqual(app.rows,[row])
        app.table.xview_moveto(0);self.root.update()
        app.select_measurement_column(SimpleNamespace(x=8,y=8))
        self.assertEqual(app.table_selected_column,'n')
        app.remove_column_button.invoke()
        app.append_table_row(row,2)
        self.assertNotIn('n',app.table.cget('displaycolumns'))
        app.show_page('ac');self.assertIn('n',app.table.cget('displaycolumns'))
        app.show_page('output');self.assertNotIn('n',app.table.cget('displaycolumns'))
        saved=json.loads((app.base/'point_columns.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['output'],list(app.table.cget('displaycolumns')))

    def test_point_columns_plus_menu_only_lists_hidden_and_empty_view_can_recover(self):
        from unittest.mock import patch
        import tkinter as tk
        app=self.app;app.show_page('output')
        with patch.object(tk.Menu,'tk_popup'),patch.object(tk.Menu,'grab_release'):
            app.show_add_column_menu()
        labels=[app.column_menu.entrycget(i,'label') for i in range(app.column_menu.index('end')+1)]
        self.assertEqual(labels,[app.table_column_titles[k] for k in app.hidden_measurement_columns()])
        hidden=app.hidden_measurement_columns()[0];app.column_menu.invoke(0)
        self.assertIn(hidden,app.table.cget('displaycolumns'))
        for key in list(app.table.cget('displaycolumns')):
            app.mark_measurement_column(key);app.remove_measurement_column()
        self.assertFalse(app.table.cget('displaycolumns'))
        app.add_measurement_column('condition')
        self.assertEqual(tuple(app.table.cget('displaycolumns')),('condition',))

    def test_result_tools_fit_narrow_window_and_table_scrolls_horizontally(self):
        # Keep the width narrow, but leave room for the table at Windows 200% DPI.
        app=self.app;app.show_page('input');self.root.geometry('1080x900');self.root.update()
        button=app.restore_result_button;parent=button.master;tools=parent.winfo_children()
        self.assertEqual(int(tools[2].grid_info()['row']),int(button.grid_info()['row']))
        self.assertLessEqual(button.winfo_x()+button.winfo_width(),parent.winfo_width())
        app.measure_tabs.select(1);self.root.update();app.table.xview_moveto(1);self.root.update()
        self.assertTrue(app.table.winfo_ismapped())
        self.assertGreater(app.table.xview()[0],0)

    def test_custom_resistance_and_frontend_fields_are_editable_saved_and_reloaded(self):
        app=self.app;app.show_page('output')
        for key,value in (('base_resistance_ohm','2400'),('collector_resistor_ohm','120')):
            self.assertEqual(str(app.config_entries[key].cget('state')),'normal')
            app.config_vars[key].set(value)
        app.front_vars['collector_amplifier_gain'].set('5')
        app.save_page_default()
        self.assertEqual(app.saved_defaults_for('npn_small')['output']['collector_resistor_ohm'],120)
        self.assertEqual(app.load_frontend_defaults().collector_amplifier_gain,5)
        self.assertIn('RC 120',app.route_text.get())
        app.show_page('input')
        self.assertIn('base_equivalent_resistance_ohm',app.frontend_entries)
        app.profile.set('PNP 小功率');app.change_profile()
        app.config_vars['ve_conversion_mode'].set('线性比例')
        app.front_vars['rx1_per_vc'].set('.2')
        self.assertIn('VE×0.2',app.route_text.get())

    def test_page_and_profile_switch_restore_rows_and_unsaved_parameters(self):
        app=self.app;app.show_page('input')
        app.config_vars['base_adc_per_v'].set('.3')
        rows=[dict(curve=0,index=0,ube_v=.6,ib_estimated_a=1e-6,uce_target_v=.5,simulated=1),
              dict(curve=1,index=0,ube_v=.65,ib_estimated_a=2e-6,uce_target_v=1,simulated=1)]
        app.rows=rows;app.plot_rows(rows)
        for i,row in enumerate(rows,1):app.append_table_row(row,i)
        app.show_page('ac');app.show_page('input')
        self.assertEqual(app.rows,rows);self.assertEqual(len(app.table.get_children()),2)
        self.assertEqual(len(app._curve_lines),2)
        app.profile.set('NPN 大功率');app.change_profile();self.assertEqual(app.rows,[])
        app.profile.set('NPN 小功率');app.change_profile()
        self.assertEqual(app.rows,rows);self.assertEqual(app.config_vars['base_adc_per_v'].get(),'0.3')
        values=[dict(zip(app.table.cget('columns'),app.table.item(item)['values'])) for item in app.table.get_children()]
        self.assertNotEqual(values[0]['curve'],values[1]['curve'])
        self.assertNotEqual(values[0]['condition'],values[1]['condition'])

    def test_load_latest_button_restores_disk_curve_without_overwriting_parameters_or_files(self):
        import csv,json
        app=self.app;app.show_page('input')
        directory=app.results/'latest';directory.mkdir()
        state=dict(measurement='input',profile='npn_small',status='complete',simulated=True,points=2,
                   finished_at=2,config=dict(base_adc_per_v=.25))
        (directory/'run.json').write_text(json.dumps(state))
        rows=[dict(curve=i,index=0,ube_v=.6+i*.01,ib_estimated_a=1e-6,uce_target_v=.5+i,
                   rx1_port_v=.15,rx2_port_v=.103,rx1_mean_code=33000,rx2_mean_code=34000) for i in range(2)]
        with (directory/'points.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        before={p.name:p.read_bytes() for p in directory.iterdir()}
        app.config_vars['base_adc_per_v'].set('.4')
        app.measurement_views.clear();app.result_by_measurement.clear();app.rows=[]
        app.restore_result_button.invoke()
        self.assertEqual(app.last_result['run_id'],'latest')
        self.assertEqual(len(app.rows),2);self.assertEqual(len(app.table.get_children()),2)
        self.assertEqual(app.config_vars['base_adc_per_v'].get(),'.4')
        self.assertEqual({name:(directory/name).read_bytes() for name in before},before)
        self.assertTrue((directory/'curve.png').exists())
        row=dict(zip(app.table.cget('columns'),app.table.item(app.table.get_children()[0])['values']))
        self.assertAlmostEqual(float(row['rx1_v']),.15)
        self.assertEqual(float(row['rx1_code']),33000)

    def test_ac_peak_voltage_roundtrip_and_pnp_vcc_annotation(self):
        app=self.app;app.show_page('ac')
        canonical=app.config_values['ac']['tx3_input_vpp']
        self.assertAlmostEqual(float(app.config_vars['tx3_input_vpp'].get()),canonical/2)
        app.config_vars['tx3_input_vpp'].set('.035')
        self.assertAlmostEqual(app.read_config()['tx3_input_vpp'],.07)
        app.save_page_default();app.show_page('input');app.show_page('ac')
        self.assertEqual(app.config_vars['tx3_input_vpp'].get(),'0.035')
        app.reset_preset()
        self.assertAlmostEqual(app.read_config()['tx3_input_vpp'],.07)
        app.profile.set('PNP 小功率');app.change_profile();app.show_page('input')
        self.assertIn('collector_channel',app.config_entries)
        self.assertNotIn('uce_tolerance_v',app.config_entries)
        app.plot_rows([dict(curve=0,ube_v=.6,ib_estimated_a=1e-6,vcc_v=2,uce_target_v=2)])
        self.assertEqual(app.ax.lines[0].get_label(),'VCC = 2 V')
        app.append_table_row(dict(ube_v=.6,ib_estimated_a=1e-6,ve_v=1.8),1)
        self.assertIn('ve',app.hidden_measurement_columns())
        app.add_measurement_column('ve')
        self.assertIn('ve',app.table.cget('displaycolumns'))
        self.assertEqual(float(app.table.item(app.table.get_children()[-1])['values'][4]),1.8)

    def test_compact_utilities_defaults_and_refinement_markers(self):
        app=self.app
        buttons=app.utility_grid.winfo_children()
        self.assertEqual({(int(b.grid_info()['row']),int(b.grid_info()['column'])) for b in buttons},
                         {(0,0),(0,1),(1,0),(1,1)})
        app.show_page('input');app.config_vars['tx1_stop_v'].set('1.5');app.save_page_default()
        self.assertTrue((app.base/'measurement_defaults.json').exists())
        app.config_vars['tx1_stop_v'].set('1.2');app.reset_preset()
        self.assertEqual(app.read_config()['tx1_stop_v'],1.5)
        app.show_page('ac')
        app.plot_rows([dict(mode='sweep',actual_freq_hz=10000,gain=100),
                       dict(mode='refine',actual_freq_hz=100000,gain=70)])
        self.assertEqual(len(app.ax.lines),2)
        refine=next(line for line in app.ax.lines if line.get_label()=='二分补测')
        self.assertEqual(refine.get_marker(),'D')
        self.assertEqual(refine.get_color(),'#e88722')

    def test_tx_enter_requires_prior_ack_and_valid_parameters(self):
        app=self.app;sent=[]
        self.assertEqual(app.tx_confirmation.cget('bg'),'#a33232')
        app.confirmed.set(True)
        self.assertEqual(app.tx_confirmation.cget('bg'),'#216657')
        app.transport=object();app.submit=lambda op,args:sent.append((op,args))
        for channel in range(3):
            app.tx_channel.set('TX{}'.format(channel+1));app.tx_mode.set('直流');app.tx_changed()
            app.last_status={'output_settings':{}}
            count=len(sent);app.tx_enter();self.assertEqual(len(sent),count)
            app.last_status={'output_settings':{str(channel):app.tx_request('apply')}}
            app.tx_vars['offset'].set('.2');app.tx_enter()
            self.assertEqual(sent[-1][1]['action'],'apply')
            self.assertEqual(sent[-1][1]['channel'],channel)
            count=len(sent);app.tx_vars['offset'].set('bad');app.tx_enter()
            self.assertEqual(len(sent),count)
        app.transport=None

    def setUp(self):
        import tkinter as tk
        from zynq_bjt.desktop import App
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'build')
        self.root = tk.Tk()
        self.app = App(self.root, workspace=self.temp.name)
        self.app.enter_workbench()  # Layout tests use a visible workbench without hardware.
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy(); self.temp.cleanup()

    def test_gpio_default_confirmed_selection_and_unknown_are_distinct(self):
        app=self.app
        self.assertTrue(all(b[0].cget('text').startswith('●') for b in app.gpio_buttons))
        self.assertIn('尚未回读',app.gpio_labels[0].cget('text'))
        app.render_status(dict(simulated=True,initialized=True,gpio=dict(output=5,sense=5)))
        self.assertTrue(app.gpio_buttons[0][1].cget('text').startswith('●'))
        self.assertTrue(app.gpio_buttons[1][0].cget('text').startswith('●'))
        app.handle_event('connection_lost','test disconnect')
        self.assertTrue(all(not b.cget('text').startswith('●') for pair in app.gpio_buttons for b in pair))

    def test_beta_dropdown_selects_one_relation_without_losing_points(self):
        app=self.app;app.show_page('beta')
        app.beta_processing.set('全部原始点')
        rows=[dict(curve=i,ib_estimated_a=(i+1)*1e-5,ic_a=(i+1)*.001,beta=100) for i in range(4)]
        app.rows=rows
        app.plot_rows(rows)
        self.assertEqual(len(app.figure.axes),1)
        for view in ('β–IC','β–IB','IC–IB'):
            app.beta_view.set(view);app.change_beta_view()
            self.assertEqual(len(app.figure.axes),1)
            self.assertEqual(len(app.ax.lines[0].get_xdata()),4)
            if view=='β–IC': self.assertEqual(list(app.ax.lines[0].get_xdata()),[1,2,3,4])
            if view!='IC–IB':
                for value in app.ax.lines[0].get_ydata():self.assertAlmostEqual(value,100)
        self.assertIs(app.rows,rows)

    def test_beta_reference_processing_matches_source_without_altering_raw_rows(self):
        app=self.app;app.show_page('beta')
        app.rows=[dict(curve=i,ib_estimated_a=(i+1)*1e-5,ic_a=(i+1)*.001) for i in range(5)]
        app.beta_view.set('β–IB');app.change_beta_view()
        self.assertEqual(len(app.ax.lines[0].get_xdata()),2)
        self.assertAlmostEqual(app.ax.lines[0].get_xdata()[0],35)
        self.assertEqual(len(app.rows),5)
        self.assertIn('5 V',app.ax.get_title())
        self.assertIn('排除前2档',app.ax.get_title())
        app.beta_processing.set('全部原始点');app.change_beta_view()
        self.assertEqual(len(app.ax.lines[0].get_xdata()),5)

    def test_ac_first_point_sets_full_view_then_only_expands_on_overflow(self):
        app=self.app
        app.show_page('ac')
        rows=[dict(actual_freq_hz=10000,gain=100)]
        app.plot_rows(rows)
        self.assertEqual(app.ax.get_ylim(),(30,120))
        self.assertEqual(app.ax.get_xlim(),(10000,5000000))
        rows.append(dict(actual_freq_hz=2000000,gain=45));app.plot_rows(rows)
        self.assertEqual(app.ax.get_ylim(),(30,120))
        rows.append(dict(actual_freq_hz=270000,gain=10));app.plot_rows(rows)
        self.assertEqual(list(app.ax.lines[0].get_xdata()),[10000,270000,2000000])
        self.assertLess(app.ax.get_ylim()[0],10)
        self.assertEqual(app.ax.get_ylim()[1],120)
        app.reset_measurement_plot();app.plot_rows([dict(actual_freq_hz=10000,gain=20)])
        self.assertEqual(app.ax.get_ylim()[1],40)
        self.assertLess(app.ax.get_ylim()[0],20)

    def test_login_requires_successful_transport_and_returns_after_disconnect(self):
        from unittest.mock import patch
        from zynq_bjt.desktop_transport import LocalTransport
        app=self.app;app.show_login();self.root.update()
        self.assertFalse(app.workbench.winfo_ismapped())
        app.source.set('PYNQ 实板');app.password.set('wrong-test-password')
        with patch('zynq_bjt.desktop.SshTransport.connect',side_effect=RuntimeError('Authentication failed')):
            app.connect()
            deadline=time.monotonic()+3
            while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        self.assertIsNone(app.transport)
        self.assertFalse(app.workbench.winfo_ismapped())
        self.assertIn('Authentication failed',app.notice.get())
        self.assertNotIn('wrong-test-password',(app.base/'desktop.log').read_text(encoding='utf-8'))
        app.source.set('离线模拟');app.connect()
        deadline=time.monotonic()+3
        while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        self.root.update()
        self.assertTrue(app.workbench.winfo_ismapped())
        self.assertFalse(app.login_view.winfo_ismapped())
        app.disconnect()
        deadline=time.monotonic()+3
        while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        self.root.update()
        self.assertTrue(app.login_view.winfo_ismapped())
        self.assertEqual(app.password.get(),'')
        self.assertFalse(app.fixture.get())

    def test_compact_confirmation_buttons_toggle_visibly(self):
        self.app.show_page('tx');self.root.update()
        button=self.app.tx_confirmation
        self.assertGreaterEqual(button.winfo_height(),24)
        self.assertLessEqual(button.winfo_height(),self.app.px(38))
        self.assertIn('点击确认',button.cget('text'))
        button.invoke()
        self.assertTrue(self.app.confirmed.get())
        self.assertIn('✓ 已确认',button.cget('text'))

    def test_parameter_tabs_preserve_edits_and_reference_segments_drive_plan(self):
        app=self.app
        self.assertEqual(list(app.parameter_panels),['基本','步进','采集','换算'])
        app.config_vars['uce_values_v'].set('.6')
        app.param_tabs.select(app.parameter_panels['步进']);self.root.update()
        self.assertFalse(app.parameter_panels['基本'].winfo_ismapped())
        self.assertTrue(app.parameter_panels['步进'].winfo_ismapped())
        app.segment_editor.load_reference()
        cfg=app.read_config()
        self.assertEqual(cfg['uce_values_v'],(.6,))
        self.assertEqual(cfg['tx1_segments_v'],'0.02:0.74:0.02;0.74:2:0.04')
        from zynq_bjt.scan import ScanConfig
        from zynq_bjt.frontend import Frontend
        self.assertEqual(len(ScanConfig(**cfg).validate(app.scope_calibration,Frontend())),69)
        app.show_page('ac')
        self.assertEqual(app.read_config()['input_adc_per_v'],9.78)
        self.assertEqual(app.segment_editor.rows[-1][0][1].get(),'5000')
        app.segment_editor.rows[-1][0][1].set('2500')
        self.assertIn('200000:2500000:100000',app.read_config()['frequency_segments_hz'])

    def test_basic_range_and_intervals_share_one_plan_and_hide_legacy_steps(self):
        from zynq_bjt.scan import ScanConfig
        from zynq_bjt.frontend import Frontend
        app=self.app;editor=app.segment_editor
        self.assertFalse({'tx1_step_v','tx1_fine_stop_v','tx1_fine_step_v'} & set(app.config_entries))
        editor.load_reference()
        app.config_vars['tx1_stop_v'].set('1.5')
        app.param_tabs.select(app.parameter_panels['步进']);self.root.update()
        self.assertEqual(editor.rows[-1][0][1].get(),'1.5')
        cfg=app.read_config()
        self.assertEqual(cfg['tx1_segments_v'],'0.02:0.74:0.02;0.74:1.5:0.04')
        self.assertEqual(cfg['tx1_stop_v'],1.5)
        plan=ScanConfig(**cfg).validate(app.scope_calibration,Frontend())
        self.assertEqual(plan[-1],1.5);self.assertNotIn(2,plan)
        editor.load_reference()
        self.assertEqual(editor.rows[-1][0][1].get(),'1.5')
        editor.rows[-1][0][1].set('1.2')
        self.assertEqual(app.read_config()['tx1_stop_v'],1.2)
        app.show_page('beta');app.show_page('input')
        self.assertEqual(app.read_config()['tx1_stop_v'],1.2)
        self.assertEqual(app.segment_editor.rows[-1][0][1].get(),'1.2')

    def test_segment_boundary_updates_neighbor_and_uniform_removes_duplicates(self):
        app=self.app;e=app.segment_editor;e.load_reference()
        e.rows[0][0][1].set('.6')
        self.assertEqual(e.value(),'0.02:0.6:0.02;0.6:2:0.04')
        e.rows[1][0][0].set('.8')
        self.assertEqual(e.value(),'0.02:0.8:0.02;0.8:2:0.04')
        e.make_uniform();self.assertEqual(len(e.rows),1)
        e.rows[0][0][2].set('.1')
        cfg=app.read_config()
        self.assertEqual(cfg['tx1_segments_v'],'0.02:2:0.1')
        self.assertEqual(cfg['tx1_step_v'],.1);self.assertEqual(cfg['tx1_fine_stop_v'],0)
        e.split_last();self.assertEqual(len(e.rows),2)
        self.assertEqual(app.read_config()['tx1_stop_v'],2)
        e.remove_row(e.rows[-1]);self.assertEqual(len(e.rows),1)
        self.assertEqual(app.read_config()['tx1_stop_v'],1.01)

    def test_partial_range_typing_is_non_destructive_and_invalid_config_is_blocked(self):
        app=self.app;e=app.segment_editor;e.load_reference();original=e.raw_value()
        app.config_vars['tx1_stop_v'].set('')
        self.assertFalse(e.sync(strict=False));self.assertEqual(e.raw_value(),original)
        with self.assertRaises(ValueError):app.read_config()
        app.config_vars['tx1_stop_v'].set('1')
        self.assertEqual(e.raw_value(),original)
        app.config_vars['tx1_stop_v'].set('1.5')
        self.assertEqual(app.read_config()['tx1_segments_v'],'0.02:0.74:0.02;0.74:1.5:0.04')
        e.rows[0][0][2].set('')
        with self.assertRaises(ValueError):app.read_config()

    def test_output_beta_and_legacy_input_plans_match_displayed_bounds(self):
        app=self.app
        for mode,lo,hi,step,segment in (
                ('beta','tx1_start_v','tx1_stop_v','tx1_step_v','tx1_segments_v'),
                ('output','tx2_control_start_v','tx2_control_stop_v','tx2_control_step_v','tx2_segments_v')):
            app.show_page(mode);self.assertNotIn(step,app.config_entries)
            app.config_vars[hi].set('.2');app.segment_editor.load_reference()
            self.assertEqual(app.read_config()[hi],.2)
            app.segment_editor.rows[-1][0][1].set('.3')
            cfg=app.read_config();self.assertEqual(cfg[hi],.3)
            self.assertEqual(float(cfg[segment].split(';')[-1].split(':')[1]),cfg[hi])
        app.show_page('input')
        app.config_values['input'].update(tx1_start_v=.02,tx1_stop_v=.3,tx1_step_v=.1,
            tx1_fine_stop_v=.4,tx1_fine_step_v=.05,tx1_segments_v='')
        app.build_parameters()
        self.assertEqual(app.read_config()['tx1_segments_v'],'0.02:0.3:0.05')

    def test_ac_annotations_distinguish_fit_from_measured_endpoints(self):
        app=self.app;app.show_page('ac')
        app.last_result=dict(state=dict(measurement='ac',profile='npn_small',simulated=True,
            ac_analysis=dict(au=100,target_gain=70.7,f_beta_hz=300000,ft_hz=30000000)))
        app.plot_rows([dict(actual_freq_hz=10000,gain=100),dict(actual_freq_hz=3000000,gain=10)])
        text=' '.join(t.get_text() for t in app.ax.texts)
        for expected in ('首点','终点','fβ=300','拟合','fT≈30','估算'):self.assertIn(expected,text)
        count=len(app._ac_artists)
        app.plot_rows([dict(actual_freq_hz=10000,gain=100),dict(actual_freq_hz=3000000,gain=10)])
        self.assertEqual(len(app._ac_artists),count)
        app.last_result['state']['ac_analysis']['f_beta_hz']=4000000
        app.plot_rows([dict(actual_freq_hz=10000,gain=100),dict(actual_freq_hz=3000000,gain=10)])
        self.assertIn('超出实测范围',' '.join(t.get_text() for t in app.ax.texts))

    def test_route_table_preserves_dac_outputs_and_sidebar_stop_resets_gpio(self):
        from zynq_bjt.desktop_transport import LocalTransport
        app=self.app
        self.assertEqual(len(app.route_buttons),8)
        self.assertEqual(len({v for v,_,_ in app.route_buttons}),8)
        self.assertNotIn('77/48',app.route_text.get())
        self.assertNotIn('\n',app.route_text.get())
        app.transport=LocalTransport(app.data,app.results)
        try:
            app.render_status(app.transport.call('initialize'))
            for channel in range(3):
                before=app.transport.call('output',dict(channel=channel,mode='dc_code',offset=2000+channel,action='start',wiring_confirmed=True))
            app.fixture.set(True)
            app.apply_relay_route('pnp_big','output')
            deadline=time.monotonic()+5
            while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertEqual(app.last_status['gpio']['output'],61)
            self.assertEqual(app.last_status['gpio']['sense'],61)
            self.assertEqual(app.last_status['outputs'],before['outputs'])
            self.assertEqual(app.last_status['output_settings'],before['output_settings'])
            self.assertFalse(app.fixture.get())
            current=[v for v,b,labels in app.route_buttons if '当前' in b.cget('text')]
            self.assertEqual(current,[61])
            app.render_gpio_selection(63)  # Output route allows 83/85=11 as well.
            self.assertEqual([v for v,b,labels in app.route_buttons if '当前' in b.cget('text')],[61])
            app.render_gpio_selection()
            self.assertFalse(any('当前' in b.cget('text') for _,b,_ in app.route_buttons))
            app.stop_button.invoke()
            deadline=time.monotonic()+5
            while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertEqual(app.last_status['gpio']['output'],0)
            self.assertEqual(app.last_status['gpio']['sense'],0)
            self.assertFalse(any(o['enabled'] for o in app.last_status['outputs']))
        finally:
            app.transport.close();app.transport=None

    def test_route_and_single_gpio_work_without_analog_initialization(self):
        from zynq_bjt.desktop_transport import LocalTransport
        from unittest.mock import patch
        app=self.app
        app.transport=LocalTransport(app.data,app.results)
        try:
            app.render_status(app.transport.call('status'))
            with patch.object(app.transport.session,'initialize',side_effect=AssertionError('Unexpected initialization')):
                app.apply_relay_route('pnp_big','output')
                deadline=time.monotonic()+5
                while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
                self.assertFalse(app.busy)
                self.assertEqual(app.last_status['gpio']['output'],61)
                self.assertFalse(app.last_status['initialized'])
                app.gpio_buttons[1][1].invoke()
                deadline=time.monotonic()+5
                while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
                self.assertEqual(app.last_status['gpio']['output'],63)
                app.stop_button.invoke()
                deadline=time.monotonic()+5
                while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
                self.assertEqual(app.last_status['gpio']['output'],0)
                self.assertFalse(app.last_status['initialized'])
        finally:
            app.transport.close();app.transport=None

    def test_sidebar_cancel_active_scan_resets_manual_gpio(self):
        from zynq_bjt.desktop_transport import LocalTransport
        app=self.app
        app.transport=LocalTransport(app.data,app.results,lambda kind,value:app.events.put(('event',kind,value)))
        try:
            app.render_status(app.transport.call('initialize'))
            app.render_status(app.transport.call('gpio',dict(mask=127,value=0x55)))
            app.config_values['input'].update(tx1_stop_v=.06,uce_values_v=(.5,),settle_s=0,
                curve_settle_s=2,frame_gap_s=0,adaptive_settle_v=0)
            app.build_parameters();app.start_scan()
            deadline=time.monotonic()+5
            while app.transport.session.board.gpio()['output']==0x55 and time.monotonic()<deadline:
                self.root.update();time.sleep(.01)
            self.assertTrue(app.busy)
            self.assertNotEqual(app.transport.session.board.gpio()['output'],0x55)
            app.stop_button.invoke()
            deadline=time.monotonic()+5
            while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertEqual(app.last_result['state']['status'],'cancelled')
            self.assertEqual(app.last_status['gpio']['output'],0)
            self.assertEqual(app.last_status['gpio']['sense'],0)
            self.assertFalse(any(o['enabled'] for o in app.last_status['outputs']))
        finally:
            app.transport.close();app.transport=None

    def test_sidebar_cancel_pending_gpio_resets_without_initialization(self):
        import threading
        from unittest.mock import patch
        from zynq_bjt.desktop_transport import LocalTransport
        app=self.app;started=threading.Event();release=threading.Event()
        app.transport=LocalTransport(app.data,app.results)
        call=app.transport.call
        def delayed_call(op,args=None,**kwargs):
            if op=='gpio':
                started.set()
                if not release.wait(5):raise TimeoutError('test did not release GPIO')
            return call(op,args,**kwargs)
        try:
            app.render_status(call('status'))
            with patch.object(app.transport,'call',side_effect=delayed_call):
                app.apply_relay_route('pnp_big','output')
                self.assertTrue(started.wait(2))
                app.stop_button.invoke();release.set()
                deadline=time.monotonic()+5
                while app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.01)
                self.assertFalse(app.busy)
                self.assertFalse(app.last_status['initialized'])
                self.assertEqual(app.last_status['gpio']['output'],0)
                self.assertEqual(app.last_status['gpio']['sense'],0)
        finally:
            release.set();app.transport.close();app.transport=None

    def test_beta_distinct_base_steps_share_ic_ib_curve_and_fit(self):
        app=self.app;app.show_page('beta')
        app.beta_processing.set('全部原始点')
        rows=[dict(curve=i,ib_estimated_a=(i+1)*1e-5,ic_a=(i+1)*.001,beta=100,simulated=True) for i in range(5)]
        app.last_result=dict(state=dict(profile='npn_small',simulated=True,measurement_basis='reference_parameters_unverified',config=dict(drop_initial_points=2),beta=dict(fit_slope_beta=100,fit_intercept_a=0)))
        app.plot_rows(rows);app.plot_rows(rows)
        self.assertEqual(len(app._curve_lines),1)
        self.assertEqual(len(app.ax.lines),2)
        self.assertEqual(len(next(iter(app._curve_lines.values())).get_xdata()),5)
        self.assertAlmostEqual(app._beta_fit_line.get_xdata()[0],30)
        self.assertIn('IB estimate',app.ax.get_xlabel())
        app.append_table_row(rows[0],1)
        values=app.table.item(app.table.get_children()[-1])['values']
        self.assertEqual(float(values[1]),10);self.assertEqual(float(values[2]),1)
        self.assertEqual(float(values[3]),100)

    def test_new_point_updates_plot_and_table_without_waiting_for_four(self):
        app = self.app
        initial_limits = (app.ax.get_xlim(), app.ax.get_ylim())
        self.assertEqual(initial_limits, ((.2, .8), (0, 10.5)))
        for n in range(1, 4):
            app.handle_event('point', dict(curve=0, ube_v=.4+n*.05, ib_estimated_a=n*1e-6,
                                          uce_target_v=.5, simulated=True))
            deadline = time.monotonic()+.35
            while time.monotonic()<deadline:
                self.root.update(); time.sleep(.005)
            self.assertEqual(len(app.ax.lines[0].get_xdata()), n)
            self.assertEqual(len(app.table.get_children()), n)
            self.assertEqual((app.ax.get_xlim(),app.ax.get_ylim()),initial_limits)
            if n == 1: first_line = app.ax.lines[0]
            else: self.assertIs(app.ax.lines[0], first_line)
        # Clearing/reopening a measurement must not keep detached old lines.
        app.ax.clear(); app.plot_rows(app.rows)
        self.assertEqual(len(app.ax.lines), 1)
        self.assertEqual(len(app.ax.lines[0].get_xdata()), 3)

    def test_curve_button_prepares_uninitialized_session_and_refreshes_status(self):
        from zynq_bjt.desktop_transport import LocalTransport
        app=self.app
        app.transport=LocalTransport(app.data,app.results,lambda kind,value:app.events.put(('event',kind,value)))
        try:
            app.render_status(app.transport.call('status'))
            app.config_values['input'].update(tx1_stop_v=.06,uce_values_v=(.5,),settle_s=0,
                curve_settle_s=0,frame_gap_s=0,adaptive_settle_v=0)
            app.build_parameters()
            app.start_scan()
            deadline=time.monotonic()+10
            while app.busy and time.monotonic()<deadline:
                self.root.update();time.sleep(.005)
            self.assertFalse(app.busy)
            self.assertIsNotNone(app.last_result,app.notice.get())
            self.assertEqual(app.last_result['state']['status'],'complete')
            self.assertTrue(app.last_status['initialized'])
            self.assertFalse(any(v['enabled'] for v in app.last_status['outputs']))
            self.assertEqual(app.tx_state.cget('text').count('停止'),3)
        finally:
            app.transport.close();app.transport=None

    def test_fixed_view_keeps_outside_data_and_all_points_is_explicit(self):
        app=self.app
        app.rows=[dict(curve=0,ube_v=.9,ib_estimated_a=12e-6,uce_target_v=.5,simulated=True)]
        app.plot_rows(app.rows)
        self.assertEqual(app.ax.get_xlim(),(.2,.8))
        self.assertEqual(app.ax.lines[0].get_xdata()[0],.9)
        self.assertIn('视图外',app.progress_text.get())
        app.show_all_points()
        self.assertGreater(app.ax.get_xlim()[1],.9)
        limits=(app.ax.get_xlim(),app.ax.get_ylim())
        app.plot_rows(app.rows)
        self.assertEqual((app.ax.get_xlim(),app.ax.get_ylim()),limits)
        app.reset_measurement_plot()
        self.assertEqual((app.ax.get_xlim(),app.ax.get_ylim()),((.2,.8),(0,10.5)))

    def test_wheel_over_nested_entry_and_dynamic_controls(self):
        from tkinter import ttk
        app = self.app
        app.build_parameters();app.param_tabs.select(app.parameter_panels['换算']); self.root.update()
        panel = app.param_scroll
        entries = []
        def visit(widget):
            if isinstance(widget, ttk.Entry): entries.append(widget)
            for child in widget.winfo_children(): visit(child)
        visit(panel.inner)
        self.assertTrue(entries)
        start = panel.canvas.yview()[0]
        entries[0].event_generate('<MouseWheel>', delta=-120); self.root.update()
        self.assertGreater(panel.canvas.yview()[0], start)
        combo = ttk.Combobox(panel.inner, values=['one', 'two'], state='readonly')
        combo.set('one'); combo.pack(); self.root.update()
        previous = panel.canvas.yview()[0]
        combo.event_generate('<MouseWheel>', delta=-120); self.root.update()
        self.assertGreater(panel.canvas.yview()[0], previous)
        self.assertEqual(combo.get(), 'one')


if __name__ == '__main__': unittest.main()
