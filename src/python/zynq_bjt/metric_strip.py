"""Compact centered instrument readouts in individual outlined cells."""
import tkinter as tk


class MetricStrip(tk.Frame):
    def __init__(self,parent,color):
        super().__init__(parent,bg='#071420')
        self.color=color;self.items=[];self.columns=None
        self.bind('<Configure>',self.arrange)

    def set(self,items):
        self.values=list(items)
        while len(self.items)<len(items):
            box=tk.Frame(self,bg='#0b1b2a',highlightbackground='#34465a',highlightthickness=1,padx=4,pady=4)
            title=tk.Label(box,bg='#0b1b2a',fg='#9aadc2',font=('Microsoft YaHei UI',8),anchor='center')
            value=tk.Label(box,bg='#0b1b2a',fg=self.color,font=('Microsoft YaHei UI',10),anchor='center')
            title.pack(fill='x');value.pack(fill='x');self.items.append((box,title,value))
        for i,(box,title,value) in enumerate(self.items):
            if i<len(items):title.configure(text=items[i][0]);value.configure(text=items[i][1])
            else:box.grid_remove()
        self.count=len(items);self.arrange()

    def arrange(self,event=None):
        width=event.width if event is not None else max(400,self.winfo_width())
        count=getattr(self,'count',0);cols=min(count,max(4,int(width/108))) if count else 1
        for c in range(8):self.columnconfigure(c,weight=1 if c<cols else 0,uniform='readout' if c<cols else '')
        for i,(box,_,_) in enumerate(self.items[:count]):box.grid(row=i//cols,column=i%cols,sticky='ew',padx=2,pady=2)
