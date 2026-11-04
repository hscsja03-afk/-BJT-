"""Offline visual QA window; no board or instrument connection."""
import json,sys,tkinter as tk
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.datasheet_extract import extract,FIELDS
from zynq_bjt.datasheet_grid import ParameterGrid
import pymupdf
out=ROOT/'report/ui_early_rin_20261102'
result=extract(ROOT/'data/datasheets/original_project/changjing_2N5401.pdf')
(out/'cleaned_2n5401.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
with pymupdf.open(result['source_file']) as doc:
    doc[1].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).save(out/'source_page_2.png')
root=tk.Tk();root.title('参数网格 · 离线视觉检查');root.geometry('1300x720')
tk.Label(root,text='长晶科技 2N5401 · 原始参数待核对 · 斜向水印已排除').pack(fill='x',pady=8)
ParameterGrid(root,result['parameters'],('page',)+FIELDS+('review_notes',),
    ('页','参数','符号','测试条件','最小','典型','最大','值/范围','单位','核对说明'),lambda i:None).pack(fill='both',expand=True)
root.mainloop()
