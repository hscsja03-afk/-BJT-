"""Wrapped, centered parameter cells with visible grid lines."""
import tkinter as tk
from tkinter import ttk


class ParameterGrid(ttk.Frame):
    def __init__(self,parent,rows,columns,headings,on_open):
        super().__init__(parent)
        canvas=tk.Canvas(self,bg='white',highlightthickness=0)
        sy=ttk.Scrollbar(self,command=canvas.yview)
        sx=ttk.Scrollbar(self,orient='horizontal',command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
        canvas.grid(row=0,column=0,sticky='nsew');sy.grid(row=0,column=1,sticky='ns');sx.grid(row=1,column=0,sticky='ew')
        body=tk.Frame(canvas,bg='#ccd5df');item=canvas.create_window(0,0,window=body,anchor='nw')
        widths=[44 if c=='page' else 210 if c=='parameter' else 220 if c=='conditions' else 190 if c=='review_notes' else 110 if c=='symbol' else 100 if c=='value' else 80 for c in columns]
        self.cells=[];self.selected=None
        for col,(name,width) in enumerate(zip(headings,widths)):
            body.columnconfigure(col,minsize=width,weight=1 if columns[col] in ('parameter','conditions','review_notes') else 0)
            tk.Label(body,text=name,bg='#e5edf6',fg='#18304d',font=('Microsoft YaHei UI',10,'bold'),padx=8,pady=10).grid(row=0,column=col,sticky='nsew',padx=1,pady=1)
        for index,row in enumerate(rows):
            widgets=[]
            for col,key in enumerate(columns):
                value='；'.join(row.get(key,[])) if key=='review_notes' else row.get(key,'')
                if key in row.get('uncertain_fields',[]):value=value.replace(' [缺字待核对]','')
                label=tk.Label(body,text=value or '—',bg='white' if index%2==0 else '#f4f7fb',fg='#18304d',
                    font=('Microsoft YaHei UI',10),anchor='center',justify='center',wraplength=0 if key in ('min','typ','max','value') else widths[col]-16,padx=8,pady=9)
                label.grid(row=index+1,column=col,sticky='nsew',padx=1,pady=1)
                label.bind('<Double-1>',lambda e,i=index:on_open(i))
                label.bind('<Button-1>',lambda e,i=index:self.select(i))
                label.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120)*3,'units'))
                widgets.append(label)
            self.cells.append(widgets)
        def size(event):
            canvas.itemconfigure(item,width=max(sum(widths)+2*len(widths),body.winfo_reqwidth(),event.width))
        canvas.bind('<Configure>',size)
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120)*3,'units'))

    def select(self,index):
        for i in (self.selected,index):
            if i is not None:
                for cell in self.cells[i]:cell.configure(bg='#d6e8ff' if i==index else ('white' if i%2==0 else '#f4f7fb'))
        self.selected=index
