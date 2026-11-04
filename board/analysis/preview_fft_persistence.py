"""使用模拟帧导出示波器新视图。"""
import math,sys
from pathlib import Path
import tkinter as tk
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop import App
out=ROOT/'report/scope_fft_persistence_20261101'
out.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.withdraw()
app=App(root,workspace=out/'preview_workspace');app.show_page('scope')
s=app.scope;s.accepting=True;s.persistence.set('24 帧')
for n in range(24):
 words=[[round(32768+5000*(1+.12*math.sin(n))*math.sin(2*math.pi*i/51.2+c+n*.08)) for i in range(1024)] for c in range(2)]
 s.receive(dict(sequence=n,words=words,sample_rates_hz=[50e6,50e6],captured_at=0,simulated=True,starts_aligned=False))
 if n==0:s.autoset()
s.stop();s.export_png(out/'persistence.png')
s.display_mode.set('FFT 频域');s.redraw();s.export_png(out/'fft.png');s.export_spectrum(out/'spectrum.csv')
for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
root.destroy()
print(out)
