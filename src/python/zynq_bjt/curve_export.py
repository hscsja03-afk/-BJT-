"""Save complete measurement plots while preserving the current display."""
import hashlib
import json
from pathlib import Path
from .result_paths import run_method


def save_curves(app, directory):
    if not app.rows or not app.last_result:return []
    directory=Path(directory);state=app.last_result['state'];saved=[]
    beta=app.beta_view.get()
    limits=(app.ax.get_xlim(),app.ax.get_ylim())
    def save(name):
        path=directory/(name+'.png')
        while path.exists() and not path.with_suffix('.source.json').exists():
            path=path.with_name(path.stem+'_auto.png')
        temporary=path.with_suffix('.tmp.png')
        app.ax.set_autoscale_on(True);app.ax.relim();app.ax.autoscale_view()
        label=app.figure.text(.99,.99,'状态：'+state.get('status','unknown'),ha='right',va='top',fontsize=8,color='#586879')
        try:
            app.figure.savefig(temporary,dpi=160)
        finally:
            label.remove()
        temporary.replace(path)
        info=dict(measurement=app.measurement,profile=state.get('profile'),status=state.get('status'),
                  simulated=state.get('simulated'),method=run_method(state),
                  beta_view=app.beta_view.get() if app.measurement=='beta' else None,
                  beta_processing=app.beta_processing.get() if app.measurement=='beta' else None,
                  png_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        path.with_suffix('.source.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
        saved.append(path.name)
    try:
        if app.measurement=='beta':
            for view,name in (('IC–IB','ic_ib'),('β–IC','beta_ic'),('β–IB','beta_ib')):
                app.beta_view.set(view);app.reset_measurement_plot();app.plot_rows(app.rows)
                save('curve_'+name)
        else:save('curve')
        app.derived_plots.save_rin(directory)
    finally:
        app.beta_view.set(beta)
        app.reset_measurement_plot();app.plot_rows(app.rows)
        app.ax.set_xlim(limits[0]);app.ax.set_ylim(limits[1]);app.canvas.draw_idle()
    return saved
