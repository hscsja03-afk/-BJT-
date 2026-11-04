"""Resolution-independent circuit illustrations for the two instrument groups.

The reference GUI reserves a centered circuit.png panel, but that asset is not
included in the supplied source. These original line illustrations follow that
placement without requiring a missing external image.
"""
import math
import tkinter as tk


class SidebarArt(tk.Canvas):
    def __init__(self, parent, kind, px):
        super().__init__(parent, width=px(190), height=px(66), bg='#142238',
                         highlightthickness=1, highlightbackground='#2c4763', bd=0)
        self.kind = kind
        self.bind('<Configure>', self.draw)

    def draw(self, event):
        self.delete('all')
        sx, sy = event.width/190, event.height/66
        width = max(1, min(sx, sy)*1.5)
        blue, green, faint = '#8fd3ff', '#54d3ac', '#25415c'
        def line(points, color=blue, **kwargs):
            self.create_line(*[v*(sx if i%2==0 else sy) for i,v in enumerate(points)],
                             fill=color, width=width, **kwargs)
        def oval(box, **kwargs):
            self.create_oval(box[0]*sx,box[1]*sy,box[2]*sx,box[3]*sy,**kwargs)
        for x in range(90,181,15):line([x,10,x,56],faint)
        for y in range(12,57,11):line([90,y,180,y],faint)
        if self.kind=='adda':
            self.create_rectangle(14*sx,13*sy,72*sx,49*sy,outline=blue,width=width)
            line([19,44,19,18,67,18],faint)
            wave=[]
            for x in range(22,66):wave.extend((x,31-9*math.sin((x-22)*math.pi/20)))
            line(wave,green)
            line([36,49,36,55,51,55,51,49]);line([28,56,59,56])
            wave=[]
            for x in range(90,181):wave.extend((x,34-15*math.sin((x-90)*math.pi/24)))
            line(wave,green)
        else:
            oval((22,12,65,55),outline=blue,width=width)
            line([9,34,34,34]);line([34,22,34,46])
            line([34,29,54,18,54,8]);line([34,39,54,50,54,59])
            line([41,43,51,48],green,arrow='last',arrowshape=(6*sx,7*sx,3*sy))
            for x,y in ((9,34),(54,8),(54,59)):
                oval((x-2,y-2,x+2,y+2),fill=green,outline='')
            line([89,10,89,57,181,57],blue)
            for amplitude in (9,19,29,39):
                points=[]
                for x in range(90,181):
                    points.extend((x,56-amplitude*(1-math.exp(-(x-90)/8))*(1+(x-90)/650)))
                line(points,green)
