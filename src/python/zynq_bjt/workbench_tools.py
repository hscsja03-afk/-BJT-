"""Desktop device library, result comparison, serial queue and read-only AI tools."""
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path
import io
import json
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
from urllib.parse import quote_plus
import webbrowser

from PIL import Image, ImageTk
from .ai_client import Client, result_context
from .polarity import ProbeConfig, PROBE_RC_OHM
from .profiles import LABELS, Profile

BG='#101827'; PANEL='#1b2a40'; FG='#edf3ff'; MUTED='#a6bad5'


def text_area(parent, height=8):
    frame=tk.Frame(parent,bg=PANEL);frame.pack(fill='both',expand=True,pady=4)
    text=tk.Text(frame,bg=PANEL,fg=FG,insertbackground=FG,wrap='word',height=height,width=30)
    bar=ttk.Scrollbar(frame,command=text.yview);bar.pack(side='right',fill='y')
    text.configure(yscrollcommand=bar.set);text.pack(fill='both',expand=True)
    return text


class ImagePane(tk.Frame):
    def __init__(self,parent):
        super().__init__(parent,bg=BG)
        self.source=None;self.zoom=1;self.photo=None
        self.canvas=tk.Canvas(self,bg='white',highlightthickness=0)
        v=ttk.Scrollbar(self,command=self.canvas.yview);v.pack(side='right',fill='y')
        h=ttk.Scrollbar(self,orient='horizontal',command=self.canvas.xview);h.pack(side='bottom',fill='x')
        self.canvas.configure(yscrollcommand=v.set,xscrollcommand=h.set)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Control-MouseWheel>',self.wheel)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120)*3,'units'))

    def set(self,source):
        self.source=source.copy() if source else None;self.zoom=1;self.draw()

    def wheel(self,event):
        self.zoom=max(.25,min(4,self.zoom*(1.15 if event.delta>0 else 1/1.15)));self.draw();return 'break'

    def draw(self):
        self.canvas.delete('all')
        if self.source is None:self.photo=None;return
        size=tuple(max(1,round(v*self.zoom)) for v in self.source.size)
        self.photo=ImageTk.PhotoImage(self.source.resize(size,Image.Resampling.LANCZOS))
        self.canvas.create_image(0,0,image=self.photo,anchor='nw');self.canvas.configure(scrollregion=(0,0,*size))


class WorkbenchTools:
    def __init__(self,app):
        from .desktop import ScrollFrame
        self.app=app;self.root=app.root;self.path=app.base/'workbench_tools.json'
        try:self.saved=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.saved={}
        self.manufacturer=tk.StringVar(value=self.saved.get('device',{}).get('manufacturer',''))
        self.model=tk.StringVar(value=self.saved.get('device',{}).get('model',''))
        self.datasheets=self.saved.get('datasheets',{});self.pdf=None;self.pdf_page=0;self.pdf_scale=1.0
        self.comparisons=[None,None];self.compare_next=0
        self.queue_items=self.saved.get('queue',[]);self.queue_running=False;self.queue_index=-1;self.queue_timer=None;self.internal=False
        self.ai_events=queue.Queue();self.ai_generation=0;self.ai_cancel=threading.Event();self.ai_client=None;self.ai_running=False
        header=app.pages['measurement'].winfo_children()[0]
        app.button(header,'自动识别',lambda:self.select('识别'),color='#285a57').pack(side='right',padx=3)
        app.button(header,'器件 / 手册',lambda:self.select('数据手册'),color='#354b6d').pack(side='right',padx=3)
        self.launcher=tk.Frame(app.measure_tabs,bg=BG);app.measure_tabs.add(self.launcher,text='工作台工具')
        self.info(self.launcher,'器件与手册、结果对比、AI 分析、一键队列及自动识别在独立窗口中打开。主窗口保留当前曲线与数据。')
        self.button(self.launcher,'打开工作台工具',lambda:self.select('队列')).pack(pady=16)
        self.page=tk.Toplevel(self.root,bg=BG);self.page.title('BJT · 器件与工作台工具')
        self.page.geometry('{}x{}'.format(min(app.px(1000),self.root.winfo_screenwidth()-80),
                                         min(app.px(720),self.root.winfo_screenheight()-100)))
        self.page.minsize(app.px(760),app.px(580));self.page.withdraw()
        self.page.protocol('WM_DELETE_WINDOW',self.page.withdraw)
        self.tabs=ttk.Notebook(self.page);self.tabs.pack(fill='both',expand=True)
        self.panels={}
        for name in ('队列','对比','AI 分析','数据手册','识别'):
            p=tk.Frame(self.tabs,bg=BG);self.tabs.add(p,text=name);self.panels[name]=p
        self.build_queue();self.build_compare();self.build_ai(ScrollFrame);self.build_pdf();self.build_probe(ScrollFrame)
        chart=app.measure_tabs.nametowidget(app.measure_tabs.tabs()[0]);bar=tk.Frame(chart,bg=BG)
        bar.pack(fill='x',before=chart.pack_slaves()[0])
        self.button(bar,'作为对比（交替左右）',self.add_next_compare).pack(side='left',padx=4,pady=3)
        self.button(bar,'一键测量队列',lambda:self.select('队列')).pack(side='left',padx=4)
        def responsive(widget):
            children=widget.winfo_children()
            if len(children)>1 and all(isinstance(child,tk.Button) for child in children):
                for child in children:child.pack_forget()
                def arrange(event=None):
                    width=max(1,widget.winfo_width());x=0;row=0;column=0
                    for child in children:
                        size=child.winfo_reqwidth()+8
                        if x and x+size>width:row+=1;column=0;x=0
                        child.grid(row=row,column=column,sticky='w',padx=2,pady=2);x+=size;column+=1
                widget.bind('<Configure>',arrange);arrange()
            else:
                for child in children:responsive(child)
        responsive(self.page);responsive(bar)
        self.root.after(80,self.pump_ai)

    def device(self):return dict(manufacturer=self.manufacturer.get().strip(),model=self.model.get().strip())
    def select(self,name):
        self.tabs.select(self.panels[name]);self.page.deiconify();self.page.lift()
    def row(self,parent):
        p=tk.Frame(parent,bg=BG);p.pack(fill='x',pady=3);return p
    def button(self,parent,label,fn):return self.app.button(parent,label,fn,color='#354b6d')
    def info(self,parent,text):self.app.label(parent,text,fg=MUTED,justify='left',wraplength=self.app.px(560)).pack(fill='x',padx=6,pady=4)
    def save(self):
        value=dict(device=self.device(),datasheets=self.datasheets,queue=self.queue_items,
                   queue_wait=self.queue_wait.get(),queue_continue=self.queue_continue.get(),
                   ai={k:v.get() for k,v in self.ai_vars.items() if k!='key'},
                   probe={k:v.get() for k,v in self.probe_vars.items()})
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(self.path)
    def close(self):
        self.cancel_queue();self.stop_ai();self.stop_pdf_extract();self.save()
        self.pdf_pane.clear()
        if self.pdf:self.pdf.close();self.pdf=None

    def build_queue(self):
        p=self.panels['队列'];r=self.row(p)
        self.button(r,'加入当前测量',self.add_queue).pack(side='left')
        self.button(r,'查看参数快照',self.queue_details).pack(side='left',padx=4)
        self.info(p,'加入时保存器件、测量项目和全部参数；执行期间锁定仪器操作。双击项目查看参数。')
        self.queue_tree=ttk.Treeview(p,columns=('order','device','profile','measurement','status'),show='headings',height=7)
        for k,t,w in zip(self.queue_tree['columns'],('顺序','器件','档位','项目','状态'),(45,100,110,85,140)):
            self.queue_tree.heading(k,text=t);self.queue_tree.column(k,width=w,stretch=True)
        self.queue_tree.pack(fill='both',expand=True);self.queue_tree.bind('<Double-1>',lambda e:self.queue_details())
        r=self.row(p)
        for label,fn in [('上移',lambda:self.move_queue(-1)),('下移',lambda:self.move_queue(1)),('删除',self.delete_queue),('清空队列',self.clear_queue)]:self.button(r,label,fn).pack(side='left',padx=2)
        r=self.row(p);self.app.label(r,'每项开始前等待 / s').pack(side='left')
        self.queue_wait=tk.StringVar(value=str(self.saved.get('queue_wait','5')));ttk.Entry(r,textvariable=self.queue_wait,width=7).pack(side='left',padx=4)
        self.queue_continue=tk.BooleanVar(value=self.saved.get('queue_continue',False));ttk.Checkbutton(r,text='普通测量失败后继续',variable=self.queue_continue).pack(side='left')
        r=self.row(p);self.button(r,'开始一键测量',self.start_queue).pack(side='left');self.button(r,'停止一键测量',self.app.stop).pack(side='left',padx=4)
        self.queue_status=tk.StringVar(value='未运行');self.app.label(r,textvariable=self.queue_status).pack(side='left')
        self.refresh_queue()
    def refresh_queue(self):
        self.queue_tree.delete(*self.queue_tree.get_children())
        for i,item in enumerate(self.queue_items):
            a=item['request'];self.queue_tree.insert('', 'end',iid=str(i),values=(i+1,a.get('device',{}).get('model',''),LABELS[a['profile']],a['measurement'],item.get('status','待运行')))
    def queue_selection(self):
        selected=self.queue_tree.selection();return int(selected[0]) if selected else None
    def add_queue(self):
        if self.queue_running:return
        try:
            args=self.app.scan_request();self.queue_items.append(dict(request=deepcopy(args),status='待运行'));self.refresh_queue();self.save()
        except Exception as e:self.app.error(e)
    def move_queue(self,delta):
        if self.queue_running:return
        i=self.queue_selection()
        if i is not None and 0<=i+delta<len(self.queue_items):
            self.queue_items[i],self.queue_items[i+delta]=self.queue_items[i+delta],self.queue_items[i];self.refresh_queue();self.queue_tree.selection_set(str(i+delta));self.save()
    def delete_queue(self):
        if self.queue_running:return
        i=self.queue_selection()
        if i is not None:self.queue_items.pop(i);self.refresh_queue();self.save()
    def clear_queue(self):
        if not self.queue_running:self.queue_items.clear();self.refresh_queue();self.save()
    def queue_details(self):
        i=self.queue_selection()
        if i is None:return
        win=tk.Toplevel(self.root);win.title('队列参数快照');win.geometry('720x600')
        text=text_area(win);text.insert('1.0',json.dumps(self.queue_items[i],ensure_ascii=False,indent=2));text.configure(state='disabled')
    def start_queue(self):
        if self.app.busy or self.queue_running:return
        try:
            if not self.app.transport or not self.app.transport.alive:raise ValueError('请先连接仪器或离线模拟')
            if not self.queue_items:raise ValueError('请先加入测量项目')
            self.wait_seconds=float(self.queue_wait.get())
            if not math.isfinite(self.wait_seconds) or not 0<=self.wait_seconds<=3600:raise ValueError('等待范围为 0～3600 秒')
            if not self.app.transport.simulated and not self.app.fixture.get():raise ValueError('请确认当前 BJT 接线与负载')
            # Prevent unattended relay power-fixture changes with the same DUT.
            if len({Profile(item['request']['profile']).big for item in self.queue_items})>1:
                raise ValueError('一键队列请使用同一功率接线档位；更换功率档位后另建队列')
            self.queue_running=True;self.queue_index=-1;self.continue_failure=self.queue_continue.get()
            for item in self.queue_items:item['status']='待运行';item.pop('result',None)
            self.next_queue()
        except Exception as e:self.app.error(e)
    def next_queue(self):
        if not self.queue_running:return
        self.queue_index+=1
        if self.queue_index>=len(self.queue_items):
            self.queue_running=False;self.queue_status.set('全部执行结束');self.app.controls();self.save();return
        self.queue_items[self.queue_index]['status']='等待';self.refresh_queue()
        self.deadline=time.monotonic()+self.wait_seconds;self.app.controls();self.wait_queue()
    def wait_queue(self):
        self.queue_timer=None
        if not self.queue_running:return
        remaining=self.deadline-time.monotonic();self.queue_status.set('第 {} 项 · 等待 {:.1f} s'.format(self.queue_index+1,max(0,remaining)))
        if remaining>0:self.queue_timer=self.root.after(min(200,max(1,round(remaining*1000))),self.wait_queue);return
        item=self.queue_items[self.queue_index];args=deepcopy(item['request'])
        self.internal=True
        try:
            self.app.profile.set(LABELS[args['profile']]);self.app.change_profile();self.app.show_page(args['measurement'])
            self.app.config_values[args['measurement']]=deepcopy(args['config']);self.app.build_parameters()
            for key,value in args['frontend'].items():
                if key in self.app.front_vars:self.app.front_vars[key].set(str(value))
            self.manufacturer.set(args.get('device',{}).get('manufacturer',''));self.model.set(args.get('device',{}).get('model',''))
            args['fixture_confirmed']=self.app.fixture.get()
            item['status']='测量中';self.refresh_queue();self.queue_status.set('第 {} 项测量中'.format(self.queue_index+1))
            self.app.execute_scan(args)
        except Exception as e:item['status']='未启动';self.cancel_queue();self.app.error(e)
        finally:self.internal=False
    def cancel_queue(self):
        if self.queue_timer is not None:self.root.after_cancel(self.queue_timer);self.queue_timer=None
        if self.queue_running:
            if 0<=self.queue_index<len(self.queue_items):self.queue_items[self.queue_index]['status']='已停止'
            self.queue_running=False;self.queue_status.set('已停止 · 后续项目未执行');self.refresh_queue();self.app.controls()
    def on_job(self,kind,op,value):
        if op=='detect' and kind=='done':self.detect_done(value)
        if op=='detect' and kind=='error':self.probe_status.set('识别中断：'+str(value))
        if op!='scan' or not self.queue_running:return
        item=self.queue_items[self.queue_index]
        state=value.get('state',{}) if kind=='done' else {}
        status=state.get('status','通信或启动失败');item['status']=status
        if kind=='done':item['result']=value.get('local_directory',value.get('directory',''))
        self.refresh_queue();self.save()
        safe=kind=='done' and 'cleanup_errors' in state and not state['cleanup_errors'] and status not in ('cleanup_failed','cancelled') and not self.app.stop_after and not self.app.close_after and self.app.transport and self.app.transport.alive
        if safe and (status=='complete' or self.continue_failure):self.queue_timer=self.root.after(0,self.next_queue)
        else:
            self.queue_running=False;self.queue_status.set('队列停止：'+status);self.app.controls()

    def build_compare(self):
        p=self.panels['对比'];r=self.row(p)
        self.button(r,'当前结果 → 左侧',lambda:self.add_compare(0)).pack(side='left')
        self.button(r,'当前结果 → 右侧',lambda:self.add_compare(1)).pack(side='left',padx=4)
        self.button(r,'AI 分析对比',lambda:self.analyze(True)).pack(side='left')
        self.button(r,'清空',self.clear_compare).pack(side='left',padx=4)
        self.info(p,'保存曲线与数据快照。左右独立 Ctrl + 滚轮缩放；拖动滚动条查看。')
        split=tk.PanedWindow(p,orient='horizontal',bg=BG,sashwidth=7);split.pack(fill='both',expand=True)
        self.compare_text=[];self.compare_images=[]
        for i in range(2):
            box=tk.Frame(split,bg=BG);split.add(box,minsize=150)
            label=self.app.label(box,'尚未加入结果',anchor='nw',justify='left',wraplength=self.app.px(300));label.pack(fill='x');self.compare_text.append(label)
            pane=ImagePane(box);pane.pack(fill='both',expand=True);self.compare_images.append(pane)
    def add_compare(self,index):
        try:
            if self.app.ac_history.displayed_reference():
                raise ValueError('当前图是历史曲线；请切到“本次采集”后加入实测结果对比')
            if self.app.busy or not self.app.last_result or not self.app.rows:raise ValueError('请先完成测量，或载入历史曲线与数据')
            buffer=io.BytesIO();self.app.figure.savefig(buffer,format='png',dpi=100,bbox_inches='tight');buffer.seek(0)
            self.comparisons[index]=dict(state=deepcopy(self.app.last_result['state']),rows=deepcopy(self.app.rows))
            self.compare_images[index].set(Image.open(buffer));s=self.comparisons[index]['state'];d=s.get('device',{})
            cfg=s.get('config',{});analysis=s.get('analysis',{})
            summary='{} {}\n{} · {} · {} 点\n{}\nRb={} Ω / Rc={} Ω'.format(d.get('manufacturer',''),d.get('model',''),s.get('profile'),s.get('measurement',self.app.measurement),len(self.app.rows),'模拟' if s.get('simulated') else '实板 / '+s.get('measurement_basis','参考换算'),cfg.get('base_resistance_ohm',s.get('frontend',{}).get('base_equivalent_resistance_ohm','—')),cfg.get('collector_resistor_ohm','—'))
            if analysis:summary+='\n'+json.dumps(analysis,ensure_ascii=False)[:260]
            self.compare_text[index].config(text=summary);self.select('对比')
        except Exception as e:self.app.error(e)
    def add_next_compare(self):
        before=self.comparisons[self.compare_next];self.add_compare(self.compare_next)
        if self.comparisons[self.compare_next] is not before:self.compare_next=1-self.compare_next
    def clear_compare(self):
        self.comparisons=[None,None]
        for label,pane in zip(self.compare_text,self.compare_images):label.config(text='尚未加入结果');pane.set(None)

    def build_ai(self,ScrollFrame):
        outer=self.panels['AI 分析'];self.ai_tabs=ttk.Notebook(outer);self.ai_tabs.pack(fill='both',expand=True)
        p=tk.Frame(self.ai_tabs,bg=BG);config_page=tk.Frame(self.ai_tabs,bg=BG)
        self.ai_tabs.add(p,text='报告 / 提问');self.ai_tabs.add(config_page,text='服务设置')
        self.ai_report_page=p
        settings=ScrollFrame(config_page)
        defaults=dict(protocol='Responses',url='https://api.openai.com/v1',model='',key='',timeout='120',effort='默认',verbosity='默认')
        defaults.update({k:v for k,v in self.saved.get('ai',{}).items() if k in defaults and k!='key'})
        self.ai_vars={k:tk.StringVar(value=v) for k,v in defaults.items()}
        choices={'protocol':['Responses','Chat Completions','Ollama'],'effort':['默认','low','medium','high'],'verbosity':['默认','low','medium','high']}
        labels={'protocol':'服务协议','url':'服务地址','model':'模型（可手填）','key':'API Key（仅本次）','timeout':'超时 / s','effort':'推理强度','verbosity':'报告详略'}
        for i,key in enumerate(defaults):
            self.app.label(settings.inner,labels[key]).grid(row=i,column=0,sticky='w',padx=6,pady=2)
            if key in choices or key=='model':widget=ttk.Combobox(settings.inner,textvariable=self.ai_vars[key],values=choices.get(key,[]),state='normal' if key=='model' else 'readonly')
            else:widget=ttk.Entry(settings.inner,textvariable=self.ai_vars[key],show='●' if key=='key' else '')
            widget.grid(row=i,column=1,sticky='ew',padx=6,pady=2)
            if key=='model':self.ai_model_combo=widget
        settings.inner.columnconfigure(1,weight=1)
        r=self.row(config_page);self.button(r,'检测服务 / 模型',self.test_ai).pack(side='left')
        self.ai_speed=tk.StringVar(value='自定义')
        speed=ttk.Combobox(r,textvariable=self.ai_speed,values=['自定义','快速','均衡','深入'],width=8,state='readonly');speed.pack(side='left',padx=4)
        speed.bind('<<ComboboxSelected>>',self.speed_changed)
        self.ai_status=tk.StringVar(value='尚未连接');self.app.label(r,textvariable=self.ai_status).pack(side='left')
        settings.pack(fill='both',expand=True)
        self.info(p,'服务地址、模型与 API Key 在“服务设置”填写。分析会将参数与抽样测点发给该服务；AI 不控制仪器。')
        r=self.row(p);self.ai_task=tk.StringVar(value='综合分析')
        ttk.Combobox(r,textvariable=self.ai_task,values=['综合分析','异常诊断','参数解释','数据质量检查'],state='readonly',width=14).pack(side='left')
        self.ai_question=tk.StringVar();entry=ttk.Entry(r,textvariable=self.ai_question);entry.pack(side='left',fill='x',expand=True,padx=4);entry.bind('<Return>',lambda e:self.analyze())
        r=self.row(p)
        for label,fn in [('分析 / 发送提问',self.analyze),('停止',self.stop_ai),('保存报告',self.save_report),('复制',self.copy_report),('清空',self.clear_report)]:self.button(r,label,fn).pack(side='left',padx=2)
        self.ai_text=text_area(p)
        self.app.label(p,textvariable=self.ai_status).pack(fill='x')
    def speed_changed(self,event=None):
        value={'快速':'low','均衡':'medium','深入':'high'}.get(self.ai_speed.get())
        if value:self.ai_vars['effort'].set(value);self.ai_vars['verbosity'].set(value)
    def start_ai(self,job):
        if self.ai_running:return
        try:
            self.ai_cancel=threading.Event();client=Client({k:v.get() for k,v in self.ai_vars.items()},self.ai_cancel)
            self.ai_client=client;self.ai_running=True;self.ai_generation+=1;generation=self.ai_generation;self.ai_started=time.monotonic();self.ai_status.set('连接服务…');self.save()
            secret=client.settings.get('key','')
            def work():
                try:
                    value=job(client,lambda text:self.ai_events.put((generation,'text',text)));self.ai_events.put((generation,'done',value))
                except Exception as e:self.ai_events.put((generation,'error',str(e).replace(secret,'[redacted]') if secret else str(e)))
            threading.Thread(target=work,daemon=True).start()
        except Exception as e:self.app.error(e)
    def test_ai(self):self.start_ai(lambda client,emit:client.models())
    def analyze(self,compare=False):
        if self.ai_running:return
        try:
            if compare:
                if not all(self.comparisons):raise ValueError('请先加入左右两个结果')
                context={k:result_context(v['state'],v['rows']) for k,v in zip(('left','right'),self.comparisons)}
                task='比较两组结果，先检查器件、模拟/实板来源、测量配置及单位是否可比'
            else:
                if self.app.busy or not self.app.last_result or not self.app.rows:raise ValueError('请先完成测量或载入最新曲线与数据')
                context=result_context(self.app.last_result['state'],self.app.rows);task=self.ai_task.get()
            question=self.ai_question.get().strip();self.select('AI 分析');self.ai_tabs.select(self.ai_report_page);self.ai_text.insert('end','\n--- '+task+' ---\n')
            self.start_ai(lambda client,emit:client.analyze(context,task,question,emit))
        except Exception as e:self.app.error(e)
    def stop_ai(self):
        self.ai_cancel.set();self.ai_generation+=1;self.ai_running=False
        client=self.ai_client;self.ai_client=None
        if client:threading.Thread(target=client.stop,daemon=True).start()
        if hasattr(self,'ai_status'):self.ai_status.set('已停止（已生成内容保留）')
    def pump_ai(self):
        try:
            while True:
                generation,kind,value=self.ai_events.get_nowait()
                if generation!=self.ai_generation:continue
                if kind=='text':self.ai_text.insert('end',value);self.ai_text.see('end')
                else:
                    self.ai_running=False
                    if kind=='done' and isinstance(value,list):self.ai_model_combo['values']=value;self.ai_status.set('服务可达 · {} 个模型'.format(len(value)))
                    elif kind=='done':self.ai_status.set('报告完成 · {:.1f} s'.format(time.monotonic()-self.ai_started))
                    else:self.ai_status.set('服务异常');self.ai_text.insert('end','\n[服务异常] '+value+'\n')
        except queue.Empty:pass
        if self.ai_running:self.ai_status.set('处理中 · {:.1f} s'.format(time.monotonic()-self.ai_started))
        if not self.app.closing:self.root.after(80,self.pump_ai)
    def save_report(self):
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.txt',filetypes=[('文本报告','*.txt'),('Markdown','*.md')])
        if path:
            try:Path(path).write_text(self.ai_text.get('1.0','end-1c'),encoding='utf-8')
            except OSError as e:self.app.error(e)
    def copy_report(self):self.root.clipboard_clear();self.root.clipboard_append(self.ai_text.get('1.0','end-1c'))
    def clear_report(self):self.stop_ai();self.ai_text.delete('1.0','end')

    def sheet_key(self):return json.dumps(self.device(),ensure_ascii=False,sort_keys=True)
    def build_pdf(self):
        p=self.panels['数据手册'];identity=self.row(p)
        self.app.label(identity,'厂家',fg=MUTED).pack(side='left')
        ttk.Combobox(identity,textvariable=self.manufacturer,values=['长晶科技','安森美','onsemi','STMicroelectronics'],width=13).pack(side='left',padx=4)
        self.app.label(identity,'型号',fg=MUTED).pack(side='left')
        ttk.Combobox(identity,textvariable=self.model,values=['2N5551','2N5401','TIP41C','TIP42C'],width=12).pack(side='left',padx=4)
        r=self.row(p)
        self.button(r,'打开已关联手册',self.open_datasheet).pack(side='left')
        self.button(r,'选择 / 关联 PDF',self.choose_pdf).pack(side='left');self.button(r,'联网搜索',self.search_datasheet).pack(side='left',padx=4)
        r=self.row(p)
        self.button(r,'上一页',lambda:self.pdf_move(-1)).pack(side='left');self.button(r,'下一页',lambda:self.pdf_move(1)).pack(side='left',padx=4)
        self.button(r,'适合宽度',lambda:self.pdf_pane.fit_width()).pack(side='left',padx=4)
        self.button(r,'提取参数 / 导出',self.show_pdf_parameters).pack(side='left',padx=4)
        self.pdf_parameters=None;self.pdf_extract_generation=0;self.pdf_extract_events=queue.Queue()
        self.pdf_extract_cancel=threading.Event();self.pdf_extract_threads=[]
        self.pdf_extract_status=tk.StringVar(value='打开手册后自动提取参数')
        self.app.label(p,textvariable=self.pdf_extract_status).pack(fill='x')
        self.root.after(100,self.pump_pdf_extract)
        self.pdf_status=tk.StringVar(value='已内置器件手册：长晶科技 / 安森美，2N5551、2N5401、TIP41C、TIP42C');self.app.label(p,textvariable=self.pdf_status,wraplength=self.app.px(560)).pack(fill='x',pady=5)
        self.info(p,'向下滚动连续阅读；Ctrl + 滚轮缩放，页面自动居中。')
        from .pdf_view import PdfPane
        self.pdf_pane=PdfPane(p,self.pdf_position);self.pdf_pane.pack(fill='both',expand=True)
    def search_datasheet(self):
        d=self.device();webbrowser.open('https://www.bing.com/search?q='+quote_plus(d['manufacturer']+' '+d['model']+' datasheet PDF'))
    def open_datasheet(self):
        self.select('数据手册');path=self.datasheets.get(self.sheet_key())
        if not path or not Path(path).is_file():
            from .datasheets import find_bundled
            path=find_bundled(self.app.data,self.device()['manufacturer'],self.device()['model'])
        if path and Path(path).is_file():self.load_pdf(path)
        else:self.pdf_status.set('此厂家 / 型号尚未关联手册，请选择本地 PDF 或联网搜索');self.choose_pdf()
    def choose_pdf(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('PDF 数据手册','*.pdf')])
        if path and self.load_pdf(path):self.datasheets[self.sheet_key()]=str(Path(path).resolve());self.save()
    def load_pdf(self,path):
        try:
            import pymupdf
            document=pymupdf.open(path)
            if document.is_encrypted or not len(document):document.close();raise ValueError('PDF 加密或没有可显示的页面')
            self.pdf_pane.clear()
            if self.pdf:self.pdf.close()
            self.pdf=document;self.pdf_page=0;self.pdf_pane.set_document(document)
            self.extract_pdf_parameters(path);return True
        except Exception as e:self.app.error('手册打开失败：'+str(e));return False
    def pdf_move(self,delta):
        if self.pdf:self.pdf_page=max(0,min(len(self.pdf)-1,self.pdf_page+delta));self.render_pdf()
    def render_pdf(self):
        self.pdf_pane.goto_page(self.pdf_page)
    def pdf_position(self,page):
        self.pdf_page=page
        if self.pdf:self.pdf_status.set('{} · 第 {} / {} 页 · 连续阅读'.format(Path(self.pdf.name).name,page+1,len(self.pdf)))

    def extract_pdf_parameters(self,path):
        self.pdf_extract_cancel.set();self.pdf_extract_cancel=threading.Event();cancel=self.pdf_extract_cancel
        self.pdf_extract_generation+=1;generation=self.pdf_extract_generation
        self.pdf_parameters=None;self.pdf_extract_status.set('正在提取参数…')
        cache=self.app.base/'datasheet_parameters'
        def work():
            try:
                from .datasheet_extract import extract_isolated
                result,target=extract_isolated(path,cache,cancel)
                self.pdf_extract_events.put((generation,result,str(target)))
            except Exception as error:self.pdf_extract_events.put((generation,None,str(error)))
        worker=threading.Thread(target=work,daemon=True)
        self.pdf_extract_threads=[t for t in self.pdf_extract_threads if t.is_alive()]+[worker]
        worker.start()

    def stop_pdf_extract(self):
        self.pdf_extract_cancel.set()
        deadline=time.monotonic()+4
        for worker in self.pdf_extract_threads:worker.join(max(0,deadline-time.monotonic()))

    def pump_pdf_extract(self):
        try:
            while True:
                generation,result,path=self.pdf_extract_events.get_nowait()
                if generation!=self.pdf_extract_generation:continue
                self.pdf_parameters=result
                self.pdf_extract_status.set(('已提取 {} 条 · {}，点击“提取参数 / 导出”'.format(len(result['parameters']),'待核对' if result.get('review_required',True) else '已对照原页') if result and result['parameters'] else
                    '未识别到参数表，请核对文本层或OCR' if result else '提取失败：'+path))
        except queue.Empty:pass
        if not self.app.closing:self.root.after(100,self.pump_pdf_extract)

    def show_pdf_parameters(self):
        if not self.pdf_parameters:
            self.app.error(self.pdf_extract_status.get());return
        from .datasheet_extract import FIELDS,export_csv
        result=self.pdf_parameters;source=self.pdf.name;generation=self.pdf_extract_generation
        window=tk.Toplevel(self.root);window.title('手册参数');window.geometry('1400x750')
        tk.Label(window,text='双击查看原页。'+('自动提取结果，缺字和条件需核对。' if result.get('review_required',True) else '本表已按对应原页核对。')).pack(fill='x')
        columns=('page',)+FIELDS+('review_notes',)
        labels=('页','参数','符号','测试条件','最小','典型','最大','值/范围','单位','核对说明')
        def jump(index):
            if generation!=self.pdf_extract_generation:self.load_pdf(source)
            self.pdf_page=result['parameters'][index]['page']-1;self.render_pdf();window.lower()
        from .datasheet_grid import ParameterGrid
        ParameterGrid(window,result['parameters'],columns,labels,jump).pack(fill='both',expand=True,padx=10,pady=8)
        def export():
            path=filedialog.asksaveasfilename(parent=window,defaultextension='.csv',filetypes=[('CSV 参数','*.csv')])
            if path:
                try:export_csv(result,path)
                except Exception as error:self.app.error(error)
        ttk.Button(window,text='导出参数 CSV',command=export).pack(pady=6)

    def build_probe(self,ScrollFrame):
        p=self.panels['识别'];self.info(p,'分别施加 NPN、PNP 小电流激励，比较电流增量，判断三极管极性。')
        scroll=ScrollFrame(p);scroll.pack(fill='both',expand=True)
        labels={'vcc_v':'测试 VCC / V（0.2～1.2）','base_currents_ua':'三个 IB / μA（逗号分隔，10～100）',
                'base_resistance_ohm':'小电流档等效电阻 / Ω','collector_resistor_ohm':'识别 RC / Ω（固定小功率档）',
                'collector_channel':'节点 ADC（0=RX1 / 1=RX2）','source_channel':'VCC ADC（0=RX1 / 1=RX2）',
                'collector_adc_per_v':'节点反馈比例','source_adc_per_v':'VCC 反馈比例','settle_s':'每点等待 / s',
                'frames_per_point':'每点独立帧数','max_current_a':'电流截止 / A','min_delta_current_a':'最小增量电流 / A',
                'min_gain':'最小增量增益','dominance_ratio':'两种接法最小响应比','max_node_drift_v':'帧间漂移上限 / V'}
        values=asdict(ProbeConfig());values.pop('profile');values.update(base_currents_ua='10, 30, 100')
        values.update(self.saved.get('probe',{}));values['collector_resistor_ohm']=PROBE_RC_OHM;self.probe_vars={k:tk.StringVar(value=str(v)) for k,v in values.items()}
        for i,(key,var) in enumerate(self.probe_vars.items()):
            self.app.label(scroll.inner,labels[key]).grid(row=i,column=0,sticky='w',padx=6,pady=3)
            ttk.Entry(scroll.inner,textvariable=var,width=19,state='readonly' if key=='collector_resistor_ohm' else 'normal').grid(row=i,column=1,sticky='ew',padx=6,pady=3)
        scroll.inner.columnconfigure(1,weight=1)
        r=self.row(p);self.button(r,'开始自动识别',self.start_detect).pack(side='left');self.button(r,'停止',self.app.stop).pack(side='left',padx=4)
        self.simulated_device=tk.StringVar(value='npn');self.app.label(r,'离线器件').pack(side='left')
        ttk.Combobox(r,textvariable=self.simulated_device,values=['npn','pnp','open','ambiguous'],width=10,state='readonly').pack(side='left')
        self.probe_status=tk.StringVar(value='尚未识别');self.app.label(p,textvariable=self.probe_status,wraplength=self.app.px(560),justify='left').pack(fill='x',pady=4)
        self.button(p,'打开最近识别数据',self.open_probe_result).pack(anchor='w')
        self.probe_result=None
    def start_detect(self):
        if self.app.busy or self.queue_running:return
        try:
            if not self.app.transport:raise ValueError('请先连接实板或离线模拟')
            from .frontend import Calibration
            args=self.app.scan_request(validate=False);config={'profile':args['profile']}
            for key,var in self.probe_vars.items():
                text=var.get().strip()
                if key=='base_currents_ua':value=tuple(float(v.strip()) for v in text.replace('，',',').split(','))
                elif key=='collector_resistor_ohm':value=PROBE_RC_OHM
                else:value=int(text) if key in ('frames_per_point','collector_channel','source_channel') else float(text)
                config[key]=value
            ProbeConfig(**config).validate(Calibration(self.app.data),self.app.read_frontend())
            args['config']=config;args['simulated_device']=self.simulated_device.get();self.save()
            transport=self.app.transport;transport.prepare();self.probe_status.set('识别中：NPN 接法 → PNP 接法')
            def work():
                result=transport.call('detect',args,timeout=180)
                try:result['local_directory']=str(transport.fetch(result,self.app.results))
                except Exception as e:result['download_error']=str(e)
                return result
            self.app.start_job('detect',work)
        except Exception as e:self.app.error(e)
    def detect_done(self,result):
        self.probe_result=result;s=result['state'];c=s['classification'];polarity=c['polarity']
        text='{} · {}'.format(s['status'],polarity.upper() if polarity!='unknown' else '无法确定')
        if s.get('error') or polarity=='unknown':text+='\n'+s.get('error',c.get('reason',''))
        for key,value in c.get('evidence',{}).items():text+='\n{}：ΔI={:.4g} mA，增量响应={:.3g}'.format(key.upper(),value['delta_a']*1000,value['response_gain'])
        self.probe_status.set(text)
        if s['status']=='complete' and polarity in ('npn','pnp') and not s['cleanup_errors']:
            key=polarity+('_big' if Profile(s['profile']).big else '_small');self.app.profile.set(LABELS[key]);self.app.change_profile()
        self.app.notice.set('自动识别：'+('无法确定' if polarity=='unknown' else polarity.upper()))
    def open_probe_result(self):
        if self.probe_result and self.probe_result.get('local_directory'):
            import os
            os.startfile(self.probe_result['local_directory'])
