from dataclasses import asdict, replace
from pathlib import Path
import csv
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop_session import Session
from zynq_bjt.polarity import ProbeConfig, classify
from zynq_bjt.ai_client import Client, result_context


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.session=Session(ROOT/'data',self.temp.name,simulated=True)
    def tearDown(self):self.session.close();self.temp.cleanup()
    def test_both_power_fixtures_and_both_polarities_have_independent_simulated_dut(self):
        for profile,rc in [('npn_small',100),('npn_big',1),('pnp_small',100),('pnp_big',.5)]:
            for device in ('npn','pnp','open','ambiguous'):
                with self.subTest(profile=profile,device=device):
                    routes=[]
                    result=self.session.detect(dict(config=dict(profile=profile,collector_resistor_ohm=rc,settle_s=0),simulated_device=device),lambda k,v:routes.append(v['gpio']) if k=='probe_point' else None)
                    state=result['state'];self.assertEqual(state['status'],'complete',state.get('error'))
                    self.assertEqual(state['classification']['polarity'],device if device in ('npn','pnp') else 'unknown')
                    self.assertEqual(routes,[4]*4+[28]*4)
                    self.assertEqual(state['config']['collector_resistor_ohm'],50)
                    self.assertEqual(state['profile'],profile)
                    self.assertTrue(all(r&96==0 for r in routes));self.assertEqual(self.session.board.gpio()['output'],0)
                    self.assertFalse(any(self.session.board.output(ch).enabled for ch in range(3)))
                    with (Path(result['directory'])/'points.csv').open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
                    self.assertIn('rx1_mean_code',rows[0]);self.assertIn('vcc_v',rows[0])
    def test_bad_request_is_rejected_before_board_initialization(self):
        for config in ({'vcc_v':9},{'base_currents_ua':(10,10,30)},{'source_channel':1}):
            with self.assertRaises(ValueError):self.session.detect({'config':config})
            self.assertIsNone(self.session.board)
    def test_cancel_between_points_resets_all_gpio_and_outputs(self):
        self.session.initialize();self.session.board.gpio(127,127)
        def emit(kind,value):
            if kind=='probe_point':self.session.cancel.set()
        result=self.session.detect({'config':{'settle_s':0}},emit)
        self.assertEqual(result['state']['status'],'cancelled');self.assertEqual(result['state']['points'],1)
        self.assertEqual(result['state']['classification']['polarity'],'unknown')
        self.assertEqual(self.session.board.gpio()['output'],0)
        self.assertFalse(any(self.session.board.enabled))
    def test_capture_failure_preserves_error_and_attempts_cleanup(self):
        self.session.initialize()
        with patch.object(self.session.board,'capture',side_effect=RuntimeError('capture failed')):
            result=self.session.detect({'config':{'settle_s':0}})
        self.assertEqual(result['state']['status'],'failed');self.assertEqual(result['state']['error'],'capture failed')
        self.assertEqual(self.session.board.gpio()['output'],0);self.assertFalse(any(self.session.board.enabled))
    def test_high_baseline_and_similar_reverse_gain_are_unknown(self):
        def rows(gains,baseline=0):
            return [dict(polarity=p,ic_a=baseline+gain*ib,ib_estimated_a=ib,noise_current_a=1e-6) for p,gain in zip(('npn','pnp'),gains) for ib in (0,1e-5,3e-5,1e-4)]
        for points in (rows((1,2)),rows((100,90)),rows((100,1),.01)):
            self.assertEqual(classify(points,ProbeConfig())['polarity'],'unknown')
    def test_current_cutoff_and_cleanup_failure_never_accept_polarity(self):
        result=self.session.detect({'config':{'settle_s':0,'max_current_a':.0001}})
        self.assertEqual(result['state']['status'],'failed');self.assertEqual(result['state']['classification']['polarity'],'unknown')
        board=self.session.board;original=board.enable;fault=[False];attempts=[]
        def enable(ch,value):
            if fault[0] and not value:
                attempts.append(ch)
                if ch==0:raise RuntimeError('mute fault')
            return original(ch,value)
        def emit(kind,value):
            if kind=='probe_point' and value['polarity']=='pnp' and value['index']==3:fault[0]=True
        with patch.object(board,'enable',side_effect=enable):result=self.session.detect({'config':{'settle_s':0}},emit)
        self.assertEqual(result['state']['status'],'cleanup_failed');self.assertEqual(result['state']['classification']['polarity'],'unknown')
        self.assertEqual(attempts,[0,1,2]);self.assertEqual(board.gpio()['output'],0)


class AiTests(unittest.TestCase):
    def test_http_protocol_payload_and_streams_using_local_server(self):
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"test-model"}]}')
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,body,self.headers.get('Authorization')))
                self.send_response(200);self.end_headers()
                if self.path.endswith('/responses'):
                    self.wfile.write(b'data: {"type":"response.output_text.delta","delta":"report"}\n\ndata: {"type":"response.completed"}\n\n')
                elif self.path.endswith('/api/chat'):
                    self.wfile.write(b'{"message":{"content":"report"},"done":true}\n')
                else:self.wfile.write(b'data: {"choices":[{"delta":{"content":"report"}}]}\n\ndata: [DONE]\n\n')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for protocol in ('Responses','Chat Completions','Ollama'):
                client=Client(dict(url='http://127.0.0.1:'+str(server.server_port),protocol=protocol,model='test-model',key='test-secret',effort='默认'),threading.Event())
                if protocol!='Ollama':self.assertEqual(client.models(),['test-model'])
                out=[];client.analyze({'rows':[{'ic_a':.001}]},'analyze','why?',out.append);self.assertEqual(''.join(out),'report')
            self.assertFalse(requests[0][1]['store']);self.assertEqual(requests[0][2],'Bearer test-secret')
            self.assertNotIn('reasoning_effort',requests[1][1])
        finally:server.shutdown();server.server_close();thread.join()
    def test_no_external_plain_http_redirect_credentials_or_partial_success(self):
        for url in ('http://example.com/v1','https://key@example.com/v1','https://example.com?key=123'):
            with self.assertRaises(ValueError):Client(dict(url=url),threading.Event())
        client=Client(dict(url='http://localhost',model='test'),threading.Event())
        with patch.object(client,'request',return_value=io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"partial"}\n')):
            with self.assertRaisesRegex(RuntimeError,'完整'):client.analyze({},'a','',lambda t:None)
    def test_context_omits_paths_secrets_and_discloses_sampling(self):
        context=result_context({'profile':'npn_small','password':'secret','directory':'private'},[{'index':i} for i in range(1000)])
        self.assertEqual(context['total_rows'],1000);self.assertEqual(context['included_rows'],120)
        self.assertEqual(context['rows'][-1]['index'],999);self.assertNotIn('secret',json.dumps(context));self.assertNotIn('private',json.dumps(context))


class ToolUiTests(unittest.TestCase):
    def test_original_project_manuals_match_manufacturer_aliases_and_open_offline(self):
        from zynq_bjt.datasheets import find_bundled
        for vendor in ('长晶科技','江苏长晶','JSCJ','安森美','onsemi','ON Semiconductor'):
            for model in ('2N5551','2N5401','TIP41C','TIP42C'):
                self.assertTrue(find_bundled(ROOT/'data',vendor,model).is_file())
        self.assertIsNone(find_bundled(ROOT/'data','长晶科技','unknown'))
        self.tools.manufacturer.set('长晶科技');self.tools.model.set('tip41c')
        with patch.object(self.tools,'choose_pdf',side_effect=AssertionError('should open bundled PDF')):
            self.tools.open_datasheet()
        self.assertIn('changjing_TIP41C.pdf',self.tools.pdf_status.get())
        self.assertGreater(len(self.tools.pdf),0)
    def setUp(self):
        import tkinter as tk
        from zynq_bjt.desktop import App
        from zynq_bjt.desktop_transport import LocalTransport
        self.temp=tempfile.TemporaryDirectory();self.root=tk.Tk();self.app=App(self.root,workspace=self.temp.name)
        self.app.transport=LocalTransport(ROOT/'data',self.app.results,lambda k,v:self.app.events.put(('event',k,v)))
        self.app.enter_workbench();self.app.controls();self.root.update();self.tools=self.app.tools
    def tearDown(self):
        self.tools.close()
        self.assertTrue(all(not t.is_alive() for t in self.tools.pdf_extract_threads))
        self.app.transport.close()
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy();self.temp.cleanup()
    def wait(self,predicate,timeout=20):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:self.root.update();time.sleep(.01)
        self.assertTrue(predicate(),self.app.notice.get())
    def prepare_scan(self):
        app=self.app;app.show_page('input');app.demo_preset();app.config_vars['tx1_stop_v'].set('.06')
        app.config_vars['uce_values_v'].set('1');app.config_vars['frames_per_point'].set('2')
        self.tools.manufacturer.set('Test Vendor');self.tools.model.set('Test BJT')
    def test_serial_queue_freezes_parameters_saves_identity_and_two_snapshots(self):
        self.prepare_scan();t=self.tools;a=self.app;t.add_queue();first=t.queue_items[0]['request']['config']['tx1_stop_v']
        a.config_vars['tx1_stop_v'].set('.1');t.add_queue();a.config_vars['tx1_stop_v'].set('.2')
        self.assertEqual(t.queue_items[0]['request']['config']['tx1_stop_v'],first)
        t.queue_wait.set('0');t.start_queue();self.wait(lambda:not t.queue_running and not a.busy)
        self.assertEqual([v['status'] for v in t.queue_items],['complete','complete'])
        state=json.loads((Path(t.queue_items[0]['result'])/'run.json').read_text(encoding='utf-8'))
        self.assertEqual(state['device']['model'],'Test BJT');self.assertIn('Test BJT',a.ax.get_title())
        t.add_compare(0);before=deepcopy(t.comparisons[0]);a.rows[0]['ube_v']=999;t.add_compare(1)
        self.assertEqual(t.comparisons[0],before);self.assertNotEqual(t.comparisons[0],t.comparisons[1])
        a.show_page('ac');self.assertIsNotNone(t.comparisons[0])
    def test_stop_while_waiting_cancels_future_tasks_and_resets_manual_gpio(self):
        self.prepare_scan();t=self.tools;a=self.app;t.add_queue();t.add_queue();t.queue_wait.set('30')
        a.transport.call('gpio',{'mask':127,'value':127});t.start_queue();self.assertTrue(t.queue_running)
        a.stop();self.wait(lambda:not a.busy);self.assertFalse(t.queue_running)
        self.assertEqual(a.transport.session.standalone_gpio,0);self.assertEqual(t.queue_items[1]['status'],'待运行')
        self.assertEqual(list(a.results.iterdir()),[])
    def test_stop_active_queue_never_starts_second_item(self):
        self.prepare_scan();t=self.tools;a=self.app;a.config_vars['settle_s'].set('.1');t.add_queue();t.add_queue();t.queue_wait.set('0')
        t.start_queue();self.wait(lambda:a.busy and a.transport.session.board is not None and any(a.transport.session.board.enabled))
        a.stop();self.wait(lambda:not a.busy and not a.stop_after)
        self.assertFalse(t.queue_running);self.assertEqual(t.queue_items[1]['status'],'待运行')
        self.assertFalse(any(a.transport.session.board.enabled));self.assertEqual(a.transport.session.board.gpio()['output'],0)
    def test_detect_selects_pnp_but_unknown_keeps_current_profile(self):
        t=self.tools;t.probe_vars['settle_s'].set('0');t.simulated_device.set('pnp');t.start_detect();self.wait(lambda:not self.app.busy)
        self.assertEqual(self.app.selected_profile().key,'pnp_small');self.assertEqual(t.probe_result['state']['classification']['polarity'],'pnp')
        self.assertNotIn('两种接法',t.probe_status.get())
        t.simulated_device.set('open');t.start_detect();self.wait(lambda:not self.app.busy)
        self.assertEqual(self.app.selected_profile().key,'pnp_small');self.assertIn('无法确定',t.probe_status.get())
    def test_probe_fixed_rc_and_big_device_selection(self):
        t=self.tools
        self.app.profile.set('PNP 大功率');self.app.change_profile()
        self.app.config_values['output']['collector_resistor_ohm']=.5
        t.probe_vars['collector_resistor_ohm'].set('.5')
        t.probe_vars['settle_s'].set('0');t.simulated_device.set('pnp')
        t.start_detect();self.wait(lambda:not self.app.busy)
        state=t.probe_result['state']
        self.assertEqual(state['config']['collector_resistor_ohm'],50)
        self.assertEqual(self.app.selected_profile().key,'pnp_big')
        self.assertEqual(self.app.config_values['output']['collector_resistor_ohm'],.5)

    def test_pdf_pages_and_settings_do_not_persist_api_key(self):
        import pymupdf
        path=Path(self.temp.name)/'test.pdf';doc=pymupdf.open();doc.new_page().insert_text((30,30),'Test datasheet');doc.new_page();doc.save(path);doc.close()
        t=self.tools;self.assertTrue(t.load_pdf(path));self.assertIsNotNone(t.pdf_pane.photo);t.pdf_move(1);self.assertEqual(t.pdf_page,1)
        t.ai_vars['key'].set('never-persist-this');t.save();self.assertNotIn('never-persist-this',t.path.read_text(encoding='utf-8'))
        t.manufacturer.set('onsemi');t.model.set('TIP41C');t.open_datasheet();self.assertEqual(Path(t.pdf.name).name,'onsemi_TIP41A_TIP41B_TIP41C.pdf')
        t.manufacturer.set('未收录厂家')
        with patch.object(t,'choose_pdf') as choose:t.open_datasheet();choose.assert_called_once()
    def test_failure_policy_never_continues_after_unknown_cleanup(self):
        self.prepare_scan();t=self.tools;t.add_queue();t.add_queue();t.continue_failure=True
        for kind,state in [('error',{}),('done',{'status':'failed','cleanup_errors':['fault']}),('done',{'status':'cancelled','cleanup_errors':[]})]:
            t.queue_running=True;t.queue_index=0;t.on_job(kind,'scan',{'state':state} if kind=='done' else 'connection lost')
            self.assertFalse(t.queue_running);self.assertIsNone(t.queue_timer)
    def test_small_tool_window_keeps_report_and_probe_controls_visible(self):
        t=self.tools;t.page.geometry('760x580');t.select('AI 分析');self.root.update()
        self.assertGreater(t.ai_text.winfo_height(),100)
        for name in ('队列','对比','数据手册','识别'):
            t.select(name);self.root.update();panel=t.panels[name]
            for child in panel.winfo_children():
                if child.winfo_ismapped():self.assertLessEqual(child.winfo_y()+child.winfo_height(),panel.winfo_height()+1)


from copy import deepcopy
if __name__=='__main__':unittest.main()
