"""Render offline UI exports; does not connect to hardware."""
import json,sys,tkinter as tk
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/python'),str(ROOT)]
from zynq_bjt.desktop import App
from sim.test_scope_workbench import frame
from zynq_bjt.measurement_views import draw_rin
from matplotlib.figure import Figure
out=ROOT/'report/ui_early_rin_20261102'
root=tk.Tk();app=App(root,workspace=out/'render_workspace');root.withdraw()
try:
    app.scope.accepting=True;app.scope.receive(frame());app.scope.autoset()
    app.scope.cursors.set(True);app.scope.cursor_times=[2.,10.];app.scope.redraw()
    app.scope.export_png(out/'scope_cards.png')
    app.scope.display_mode.set('频域 FFT');app.scope.draw_fft();app.scope.export_png(out/'fft_cards.png')
    history=json.loads((ROOT/'data/pnp_ac_history/index.json').read_text(encoding='utf8'))['records']
    record=next(r for r in history if r['id']=='pnp_small_20260813_200907')
    fig=Figure(figsize=(10,6),layout='constrained');ax=fig.add_subplot(111);draw_rin(ax,[],{},record)
    fig.savefig(out/'pnp_historical_rin.png',dpi=150)
finally:
    app.tools.close()
    for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
    root.destroy()
