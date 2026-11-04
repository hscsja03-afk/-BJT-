"""Continuous, centered PDF canvas; render only nearby pages."""
import bisect
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk


class PdfPane(tk.Frame):
    def __init__(self, parent, on_page=lambda page:None):
        super().__init__(parent,bg='white')
        self.document=None;self.on_page=on_page;self.zoom=1.0
        self.pages=[];self.photos={};self.photo=None;self._paint_job=None;self._resize_job=None
        self.canvas=tk.Canvas(self,bg='white',highlightthickness=0,yscrollincrement=1)
        self.vbar=ttk.Scrollbar(self,command=self.canvas.yview);self.vbar.pack(side='right',fill='y')
        self.hbar=ttk.Scrollbar(self,orient='horizontal',command=self.canvas.xview);self.hbar.pack(side='bottom',fill='x')
        self.canvas.configure(yscrollcommand=self._scrolled,xscrollcommand=self.hbar.set)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self._resize)
        self.canvas.bind('<MouseWheel>',self._wheel)
        self.canvas.bind('<Control-MouseWheel>',self._zoom_wheel)
        self.canvas.bind('<Button-1>',lambda e:self.canvas.focus_set())
        self.canvas.bind('<Next>',lambda e:self.canvas.yview_scroll(1,'pages'))
        self.canvas.bind('<Prior>',lambda e:self.canvas.yview_scroll(-1,'pages'))
        self.bind('<Destroy>',self._destroy,add='+')

    def clear(self):
        for name in ('_paint_job','_resize_job'):
            job=getattr(self,name)
            if job is not None:self.after_cancel(job);setattr(self,name,None)
        self.document=None;self.pages=[];self.photos={};self.photo=None;self.canvas.delete('all')

    def _destroy(self,event):
        if event.widget is self:
            try:self.clear()
            except tk.TclError:pass

    def set_document(self,document):
        self.clear();self.document=document;self.zoom=1.0
        self.sizes=[(p.rect.width,p.rect.height) for p in document]
        self.layout(keep_position=False)

    def _resize(self,event):
        if self._resize_job is not None:self.after_cancel(self._resize_job)
        self._resize_job=self.after(100,self.layout)

    def fit_width(self):
        self.zoom=1.0;self.layout()

    def layout(self,keep_position=True):
        if self._resize_job is not None:self.after_cancel(self._resize_job)
        self._resize_job=None
        if self.document is None:return
        page,part=self.position() if keep_position else (0,0)
        width=max(300,self.canvas.winfo_width()) if self.canvas.winfo_width()>1 else 800
        self.scale=(width-24)/max(w for w,h in self.sizes)*self.zoom
        self.content_width=max(width,round(max(w for w,h in self.sizes)*self.scale)+24)
        self.canvas.delete('all');self.photos={};self.photo=None;self.pages=[]
        y=12
        for w,h in self.sizes:
            w,h=round(w*self.scale),round(h*self.scale);x=(self.content_width-w)/2
            self.canvas.create_rectangle(x,y,x+w,y+h,fill='white',outline='#e3e7ed')
            item=self.canvas.create_image(x,y,anchor='nw')
            self.pages.append(dict(x=x,y=y,width=w,height=h,item=item));y+=h+18
        self.total_height=y;self.starts=[p['y'] for p in self.pages]
        self.canvas.configure(scrollregion=(0,0,self.content_width,y))
        self.canvas.xview_moveto(0 if self.zoom<=1 else (self.content_width-width)/2/self.content_width)
        self.canvas.yview_moveto((self.pages[page]['y']+part*self.pages[page]['height']-12)/y)
        self.paint()

    def position(self):
        if not self.pages:return 0,0
        top=max(0,self.canvas.canvasy(0))
        i=max(0,min(len(self.pages)-1,bisect.bisect_right(self.starts,top+13)-1))
        return i,max(0,min(1,(top-self.pages[i]['y'])/self.pages[i]['height']))

    def goto_page(self,page):
        if not self.pages:return
        page=max(0,min(len(self.pages)-1,page))
        self.canvas.yview_moveto(max(0,self.pages[page]['y']-12)/self.total_height)
        self.paint();self.on_page(page)

    def _scrolled(self,first,last):
        self.vbar.set(first,last)
        if self._paint_job is None:self._paint_job=self.after_idle(self.paint)

    def _wheel(self,event):
        steps=-int(event.delta/120) if abs(event.delta)>=120 else (-1 if event.delta>0 else 1)
        self.canvas.yview_scroll(steps*84,'units');return 'break'

    def _zoom_wheel(self,event):
        self.zoom=max(.4,min(3,self.zoom*(1.15 if event.delta>0 else 1/1.15)))
        self.layout();return 'break'

    def paint(self):
        if self._paint_job is not None:self.after_cancel(self._paint_job);self._paint_job=None
        if self.document is None or not self.pages:return
        import pymupdf
        top=self.canvas.canvasy(0);height=max(300,self.canvas.winfo_height())
        visible={i for i,p in enumerate(self.pages) if p['y']+p['height']>=top-height*.25 and p['y']<=top+height*1.25}
        for i in set(self.photos)-visible:
            self.canvas.itemconfigure(self.pages[i]['item'],image='');del self.photos[i]
        for i in sorted(visible):
            if i in self.photos:continue
            p=self.pages[i]
            pix=self.document[i].get_pixmap(matrix=pymupdf.Matrix(self.scale,self.scale),alpha=False,colorspace=pymupdf.csRGB)
            im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            if im.size!=(p['width'],p['height']):im=im.resize((p['width'],p['height']),Image.Resampling.LANCZOS)
            self.photos[i]=ImageTk.PhotoImage(im)
            self.canvas.itemconfigure(p['item'],image=self.photos[i])
        page,_=self.position();self.photo=self.photos.get(page)
        self.on_page(page)
