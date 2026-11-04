"""LCD 页面与离线触摸预览。图层数据可交给新版 RTL 显示。"""
import argparse
import math
from pathlib import Path
from functools import lru_cache

PALETTE = ('0D1626', '1C2A40', 'E8F0FF', '92A8C9', '2463C5', '087F69',
           '41DBA3', 'FFBE55', 'EF7373', 'B69CFF', '30445F', 'FFFFFF',
           '763A20', 'FFDBA8', '60C8FF', '000000')
WIDTH, HEIGHT = 512, 300
NATIVE_SIZE = (1024,600)


class ScaledDraw:
    """缩放绘图坐标，在目标分辨率直接栅格化，不放大已画好的位图。"""
    def __init__(self,image,scale):
        from PIL import ImageDraw
        self.draw,self.scale=ImageDraw.Draw(image),scale
        self.rgb=image.mode=='RGB'

    def __getattr__(self,name):
        def paint(coords,**kwargs):
            coords=[tuple(v*self.scale for v in xy) if isinstance(xy,(tuple,list)) else xy*self.scale
                    for xy in coords]
            for key in ('width','radius'):
                if key in kwargs:kwargs[key]=max(1,round(kwargs[key]*self.scale))
            if self.rgb:
                for key in ('fill','outline'):
                    if key in kwargs and isinstance(kwargs[key],int):kwargs[key]=tuple(bytes.fromhex(PALETTE[kwargs[key]]))
            return getattr(self.draw,name)(coords,**kwargs)
        return paint


@lru_cache(maxsize=8)
def display_font(size, bold=False):
    from PIL import ImageFont
    path=Path('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc')
    if not path.exists():raise RuntimeError('Chinese font missing: '+str(path))
    return ImageFont.truetype(str(path),size)


@lru_cache(maxsize=256)
def text_mask(value, size, bold=False):
    """缓存灰度字形；不在索引图上直接画二值文字。"""
    from PIL import Image, ImageDraw
    font = display_font(size,bold)
    bounds = font.getbbox(value)
    mask = Image.new('L', (max(1,bounds[2]-bounds[0]), max(1,bounds[3]-bounds[1])))
    ImageDraw.Draw(mask).text((-bounds[0],-bounds[1]), value, font=font, fill=255)
    return mask, bounds


@lru_cache(maxsize=16)
def text_blends(color):
    """覆盖率映射回实屏固定16色，不抖动，保持静态文字逐帧一致。"""
    import numpy as np
    palette = np.array([list(bytes.fromhex(c)) for c in PALETTE], dtype=np.float32)
    alpha = np.arange(256, dtype=np.float32)[None,:,None]/255
    rgb = palette[:,None,:]*(1-alpha)+palette[color]*alpha
    distance = ((rgb[:,:,None,:]-palette[None,None,:,:])**2).sum(axis=3)
    # 中性文字只用蓝灰色阶，彩色文字只用同色系，避免边缘出现杂色。
    neutral = (0,1,10,3,2,11,15)
    families = {4:(0,1,10,4,14), 6:(0,1,5,6), 7:(0,1,12,7,13),
                8:(0,1,12,8), 9:(0,1,10,9), 14:(0,1,10,4,14)}
    allowed = neutral if color in neutral else families.get(color,(0,1,color))
    distance[:,:,[i for i in range(16) if i not in allowed]] = float('inf')
    # 背景本身始终是候选，选中按钮上的字也不会出现深色光边。
    for background in range(16):
        distance[background,:,background] = ((rgb[background]-palette[background])**2).sum(axis=1)
    result = distance.argmin(axis=2).astype(np.uint8)
    result[:,0] = np.arange(16)
    result[:,255] = color
    return result


def smooth_text(image, xy, value, color=2, size=13, max_width=None, bold=False):
    import numpy as np
    from PIL import Image
    value = str(value)
    if not value: return
    font = display_font(size,bold)
    if max_width is not None and font.getlength(value) > max_width:
        while value and font.getlength(value+'…') > max_width: value = value[:-1]
        value += '…'
    mask, bounds = text_mask(value, size,bold)
    x, y = round(xy[0]+bounds[0]), round(xy[1]+bounds[1])
    left, top = max(0,x), max(0,y)
    right, bottom = min(image.width,x+mask.width), min(image.height,y+mask.height)
    if right <= left or bottom <= top: return
    region = (left,top,right,bottom)
    background = np.asarray(image.crop(region))
    coverage = np.asarray(mask.crop((left-x,top-y,right-x,bottom-y)))
    if image.mode=='RGB':
        alpha=coverage.astype(np.uint32)[:,:,None]
        ink=np.array(list(bytes.fromhex(PALETTE[color])),dtype=np.uint32)
        blended=(background.astype(np.uint32)*(255-alpha)+ink*alpha+127)//255
        image.paste(Image.fromarray(blended.astype(np.uint8)),region)
        return
    image.paste(Image.frombytes(
        'P',(right-left,bottom-top),text_blends(color)[background,coverage].tobytes()),region)


def smooth_curve(image, coords, color, region, width=2):
    """只对线条覆盖率抗锯齿；原始测点和固定调色板不变。"""
    import numpy as np
    from PIL import Image, ImageDraw
    if not coords:return
    left,top,right,bottom=region
    size=(right-left,bottom-top)
    supersample=2
    mask=Image.new('L',(size[0]*supersample,size[1]*supersample))
    draw=ImageDraw.Draw(mask)
    points=[((x-left)*supersample,(y-top)*supersample) for x,y in coords]
    if len(points)>1:
        draw.line(points,fill=255,width=width*supersample,joint='curve')
    else:
        x,y=points[0];r=width*supersample/2
        draw.ellipse((x-r,y-r,x+r,y+r),fill=255)
    mask=mask.resize(size,Image.Resampling.LANCZOS)
    background=np.asarray(image.crop(region))
    if image.mode=='RGB':
        alpha=np.asarray(mask,dtype=np.uint32)[:,:,None]
        ink=np.array(list(bytes.fromhex(PALETTE[color])),dtype=np.uint32)
        pixels=(background.astype(np.uint32)*(255-alpha)+ink*alpha+127)//255
        image.paste(Image.fromarray(pixels.astype(np.uint8)),region)
        return
    pixels=text_blends(color)[background,np.asarray(mask)]
    image.paste(Image.frombytes('P',size,pixels.tobytes()),region)


def frame_pixels(image):
    if image.mode=='RGB':
        import numpy as np
        rgb=np.asarray(image,dtype=np.uint16)
        return (((rgb[:,:,0]>>3)<<11)|((rgb[:,:,1]>>2)<<5)|(rgb[:,:,2]>>3)).astype('<u2').tobytes()
    return image.tobytes()


def image_words(image):
    """打包两个4位像素；先关闭图层，写完后打开。"""
    if image.mode != 'P' or image.size not in ((WIDTH, HEIGHT),NATIVE_SIZE):
        raise ValueError('Expected a 512x300 or 1024x600 indexed image')
    native=image.size==NATIVE_SIZE
    pixels = image.tobytes()
    if any(p > 15 for p in pixels):
        raise ValueError('LCD palette has 16 colors')
    command,shift,mode=(0xa0000000,19,2) if native else (0x80000000,17,0)
    return [0xC0000000|mode] + [command | i//2 | ((pixels[i] | pixels[i+1]<<4)<<shift)
                           for i in range(0, len(pixels), 2)] + [0xC0000001|mode]


def unpack_words(words,native=False):
    from PIL import Image
    image = Image.new('P', NATIVE_SIZE if native else (WIDTH, HEIGHT))
    image.putpalette([v for c in PALETTE for v in bytes.fromhex(c)] + [0]*720)
    pixels = bytearray(image.width*image.height)
    for word in words:
        if word >> 30 == 2:
            if bool(word & 0x20000000)!=native:raise ValueError('LCD pixel format mismatch')
            address = word & (0x7ffff if native else 0x1ffff)
            if address >= len(pixels)//2:
                raise ValueError('Pixel address out of range')
            pair = (word >> (19 if native else 17)) & 255
            pixels[address*2:address*2+2] = bytes((pair & 15, pair >> 4))
    image.frombytes(bytes(pixels))
    return image


class LcdDemo:
    """仅模拟本机状态，不创建硬件连接。"""
    def __init__(self,native=False,rgb565=False):
        self.native = native or rgb565
        self.rgb565 = rgb565
        self.page = 'RX'
        self.tx = 0
        self.volts = [.5, .5, .035]
        self.enabled = [False]*3
        self.gpio = 0
        self.mode = '输出'
        self.pnp = False
        self.running = False
        self.has_data = False
        self.phase = 0
        self.buttons = []
        self.live = False
        self.note = ''
        self.rx_trace = None
        self.rx_units = '电压 / V'
        self.wave = 'sine'
        self.frequency = 100000
        self.sample_count = 4096
        self.sample_stride = 1
        self.big = False
        self.saved_plot = None
        self.tx_preview_hidden = False

    def action(self, name):
        if name in ('TX', 'RX', 'IO', 'BJT'):
            self.page = name
            self.running = False
            self.has_data = False
        elif name == 'channel': self.tx = (self.tx+1)%3
        elif name == 'wave':
            waves = ('sine', 'square', 'triangle')
            self.wave = waves[(waves.index(self.wave)+1)%3]
            if self.wave != 'sine': self.frequency = min(self.frequency, 1000000)
        elif name == 'frequency':
            frequencies = (10000, 100000, 500000, 1000000, 2000000, 3000000, 4000000, 5000000)
            if self.wave != 'sine': frequencies = frequencies[:4]
            self.frequency = next((v for v in frequencies if v>self.frequency),frequencies[0])
        elif name == 'points':
            choices = (256, 512, 1024, 2048, 4096)
            self.sample_count = choices[(choices.index(self.sample_count)+1)%len(choices)]
        elif name == 'stride':
            self.sample_stride = next((v for v in (1,4,16,64,256) if v>self.sample_stride),1)
        elif name == 'size':
            self.big = not self.big
            self.has_data = False
        elif name in ('minus', 'plus'):
            step = .005 if self.tx == 2 else .05
            self.volts[self.tx] = round(max(0, min(1.8, self.volts[self.tx] + (step if name=='plus' else -step))), 3)
        elif name == 'power': self.enabled[self.tx] = not self.enabled[self.tx]
        elif name == 'stop':
            self.running = False
            self.enabled = [False]*3
            self.gpio = 0
        elif name == 'single':
            self.has_data = True
            self.phase += .25
            self.running = False
        elif name == 'run':
            self.running = not self.running
            self.has_data = True
        elif name == 'polarity':
            self.pnp = not self.pnp
            self.has_data = False
        elif name == 'mode':
            modes = ['输入', '输出', 'β', '交流', 'Early', 'Rin']
            self.mode = modes[(modes.index(self.mode)+1)%4]
            self.has_data = False
        elif name.startswith('io'): self.gpio ^= 1 << int(name[2:])

    def touch(self, x, y):
        # 触摸坐标使用实际屏幕的1024x600尺寸。
        for box, action in self.buttons:
            if box[0] <= x/2 < box[2] and box[1] <= y/2 < box[3]:
                self.action(action)
                return action
        return None

    def render(self):
        from PIL import Image, ImageDraw
        scale=2 if self.native else 1
        image = Image.new('RGB',NATIVE_SIZE,'#'+PALETTE[0]) if self.rgb565 else unpack_words([],native=self.native)
        draw = ScaledDraw(image,scale)
        button_size=13 if self.native else 14
        button_font=display_font(button_size*scale,not self.native)
        self.buttons = []

        def text(x, y, value, color=2, large=False, max_width=None, small=False):
            size=(20 if large else 12 if small else 13) if self.native else (20 if large else 13 if small else 14)
            smooth_text(image,(x*scale,y*scale),value,color if self.native else 2 if color==3 else color,
                        size*scale,(max_width if max_width is not None else 496-x)*scale,
                        bold=large or not self.native)

        def button(box, label, action, selected=False):
            draw.rounded_rectangle(box, radius=4, fill=4 if selected else 1)
            if self.native and selected:
                draw.line((box[0]+8,box[3]-1,box[2]-8,box[3]-1),fill=14,width=.5)
            bounds = button_font.getbbox(label)
            smooth_text(image,(((box[0]+box[2])*scale-(bounds[2]-bounds[0]))/2-bounds[0],
                              ((box[1]+box[3])*scale-(bounds[3]-bounds[1]))/2-bounds[1]),
                        label,size=button_size*scale,max_width=(box[2]-box[0]-8)*scale,bold=not self.native)
            self.buttons.append((box, action))

        text(16, 10, {'TX':'信号输出', 'RX':'双路波形', 'IO':'数字控制', 'BJT':'三极管特性'}[self.page], large=True)
        text(368 if self.native else 360, 15, '实板 · 参考换算' if self.live else '离线 · 模拟数据', 3,small=True)
        draw.line((16, 40, 496, 40), fill=10)
        for i, name in enumerate(('TX', 'RX', 'IO', 'BJT')):
            button((16+i*98, 263, 106+i*98, 294), name, name, self.page==name)
        button((416, 263, 496, 294), '全部停止', 'stop')

        def plot(curves, xlabel, ylabel, xlim, ylim):
            left, top, right, bottom = (54,106,490,220) if self.native else (64,122,484,222)
            if self.native and self.page=='TX' and self.tx==2:top=122
            for i in range(6):
                x = left+(right-left)*i/5
                draw.line((x, top, x, bottom), fill=1 if self.native else 10,width=.5)
            for i in range(5):
                y = top+(bottom-top)*i/4
                draw.line((left, y, right, y), fill=1 if self.native else 10,width=.5)
            if self.native:
                draw.rectangle((left,top,right,bottom),outline=10,width=.5)
                if ylim[0]<0<ylim[1]:
                    zero=bottom+ylim[0]/(ylim[1]-ylim[0])*(bottom-top)
                    draw.line((left,zero,right,zero),fill=10,width=.5)
                text(344,87,ylabel,3,small=True)
                text(230,223,xlabel,3,small=True,max_width=160)
                text(12,top-5,f'{ylim[1]:.3g}',3,small=True,max_width=40)
                text(12,bottom-12,f'{ylim[0]:.3g}',3,small=True,max_width=40)
                text(left,223,f'{xlim[0]:.3g}',3,small=True,max_width=120)
                end=f'{xlim[1]:.3g}'
                text(right-display_font(24).getlength(end)/scale,223,end,3,small=True)
            else:
                text(344, 88, ylabel, 3)
                text(344, 225, xlabel, 3)
                text(16, top, f'{ylim[1]:.3g}', 3,small=True)
                text(16, bottom-12, f'{ylim[0]:.3g}', 3,small=True)
                text(left, 225, f'{xlim[0]:.3g}', 3,small=True)
                text(right-28, 208, f'{xlim[1]:.3g}', 3,small=True)
            for points, color in curves:
                coords = [(left+(x-xlim[0])/(xlim[1]-xlim[0])*(right-left),
                           bottom-(y-ylim[0])/(ylim[1]-ylim[0])*(bottom-top)) for x, y in points]
                if self.native:
                    smooth_curve(image,[(x*scale,y*scale) for x,y in coords],color,
                                 tuple(v*scale for v in (left,top,right+1,bottom+1)))
                    continue
                # Clip the drawing layer so an outlier cannot cover controls.
                layer = Image.new('P', image.size); layer.putpalette(image.getpalette())
                painter = ScaledDraw(layer,scale)
                if len(coords)>1: painter.line(coords, fill=color, width=2)
                elif coords: painter.ellipse((coords[0][0]-1,coords[0][1]-1,coords[0][0]+1,coords[0][1]+1),fill=color)
                region = tuple(v*scale for v in (left,top,right+1,bottom+1))
                crop = layer.crop(region)
                mask = crop.point([0]+[255]*255,'L')
                image.paste(crop,region,mask)

        if self.page == 'TX':
            button((16, 50, 110, 80), f'TX{self.tx+1}  切换', 'channel')
            button((122, 50, 178, 80), '−', 'minus')
            button((190, 50, 246, 80), '+', 'plus')
            button((370, 50, 496, 80), '已开启' if self.enabled[self.tx] else '开启', 'power', self.enabled[self.tx])
            v = self.volts[self.tx]
            text(258, 57, f'{2*v:.3f} Vpp' if self.tx==2 else f'{v:.3f} V', 7)
            if self.tx == 2:
                button((16,84,110,114), {'sine':'正弦','square':'方波','triangle':'三角波'}[self.wave], 'wave')
                button((122,84,270,114), f'{self.frequency/1000:g} kHz  切换', 'frequency')
                duration = 2e6/self.frequency
                def shape(t):
                    if self.wave=='square': return 1 if t%1<.5 else -1
                    if self.wave=='triangle': return 1-4*abs(t%1-.5)
                    return math.sin(t*2*math.pi)
                points = [(i/200*duration, v*shape(i/100)) for i in range(201)]
            else:
                duration=10;points=[(0,v),(duration,v)]
            bound=max(.05,abs(v)*1.2)
            plot([(points, 6)], '时间 / µs', '', (0, duration), (-bound,bound))
            text(16,239,'设定预览',3)
            if self.tx_preview_hidden:
                draw.rectangle((48,122,484,222),fill=0)
                text(120,158,'此输出参数请在上位机查看 / 修改',7)
        elif self.page == 'IO':
            for i, pin in enumerate((87, 85, 83, 81, 79, 77, 48)):
                col, row = i%4, i//4
                on = bool(self.gpio & (1<<i))
                button((16+col*122, 62+row*78, 126+col*122, 119+row*78),
                       f'{pin}   {"高" if on else "低"}', f'io{i}', on)
            text(16, 234, '点击切换电平', 3)
        else:
            if self.page == 'RX':
                button((16, 50, 90, 80), '单次', 'single')
                button((100, 50, 174, 80), '暂停' if self.running else '连续', 'run', self.running)
                if self.native:
                    button((184,50,322,80),f'{self.sample_count} 点','points')
                    button((332,50,496,80),f'抽取 ×{self.sample_stride}','stride')
                    draw.line((16,95,30,95),fill=6,width=1)
                    draw.line((94,95,108,95),fill=7,width=1)
                    text(36,85,'RX1',6,small=True);text(114,85,'RX2',7,small=True)
                else:
                    text(260, 57, 'RX1', 6); text(320, 57, 'RX2', 7)
                    button((16,84,160,114), f'{self.sample_count} 点', 'points')
                    button((172,84,316,114), f'抽取 ×{self.sample_stride}', 'stride')
                curves = []
                if self.has_data:
                    if self.live and self.rx_trace:
                        curves=[(points,color) for points,color in zip(self.rx_trace,(6,7))]
                    elif not self.live:
                        for amplitude, offset, color in ((.8, 0, 6), (.45, 1.2, 7)):
                            curves.append(([(i/20, amplitude*math.sin(i*math.pi/40+self.phase+offset)) for i in range(401)], color))
                xmax=max((points[-1][0] for points,color in curves),default=20)
                bound=max(1,max((abs(y) for points,color in curves for x,y in points),default=1))
                plot(curves, '时间 / µs', self.rx_units, (0, xmax), (-bound, bound))
            else:
                button((16, 50, 90, 80), 'PNP' if self.pnp else 'NPN', 'polarity')
                button((100, 50, 190, 80), self.mode+'  切换', 'mode')
                button((200, 50, 294, 80), '大功率' if self.big else '小功率', 'size')
                button((370, 50, 496, 80), '读取记录' if self.live else '示意曲线', 'single')
                curves = []
                if self.mode == '输入':
                    xlabel, ylabel, xmax, ymax = ('UEB / V' if self.pnp else 'UBE / V'), 'IB / µA', .8, 100
                    values = [[(i*.004, .004*math.exp(i*.004/.08)) for i in range(201)]]
                elif self.mode == '输出':
                    xlabel, ylabel, xmax, ymax = ('UEC / V' if self.pnp else 'UCE / V'), 'IC / mA', 5, 10
                    values = [[(i*.025, k*(1-math.exp(-i*.025/.2))*(1+i*.025/80)) for i in range(201)] for k in (2, 4, 6, 8)]
                elif self.mode == 'β':
                    xlabel, ylabel, xmax, ymax = 'IC / mA', 'β', 10, 200
                    values = [[(i*.05, 140*(1-math.exp(-i/12))/(1+(i/330)**2)) for i in range(201)]]
                elif self.mode == '交流':
                    xlabel, ylabel, xmax, ymax = '频率 / kHz', '|β|', 1000, 200
                    values = [[(i*5, 140/math.sqrt(1+(i*5/250)**2)) for i in range(201)]]
                elif self.mode == 'Rin':
                    xlabel, ylabel, xmax, ymax = '频率 / kHz', 'Rin / Ω', 5000, 2000
                    values = [[(i*25, 1500/math.sqrt(1+(i/30)**2)) for i in range(201)]]
                else:
                    xlabel, ylabel, xmax, ymax = 'UCE / V', 'IC / mA', 5, 10
                    values = [[(-80,0),(5,k*(1+5/80))] for k in (2,4,6,8)]
                if self.has_data and not self.live: curves = [(v, c) for v, c in zip(values, (6, 7, 9, 14))]
                xmin=-80 if self.mode=='Early' else 0
                if self.live and self.has_data and self.saved_plot:
                    saved=self.saved_plot
                    curves=saved['curves'];xlabel=saved['xlabel'];ylabel=saved['ylabel']
                    xmin,xmax=saved['xlim'];ymin,ymax=saved['ylim']
                    text(16,85,saved['label'],3,max_width=308)
                else:ymin=0
                plot(curves, xlabel, ylabel, (xmin, xmax), (ymin, ymax))
            if not self.has_data: text(200, 150, '等待采集' if self.page=='RX' else '点击读取记录' if self.live else '等待预览', 3)
        if self.note:
            draw.rectangle((16,239,496,258),fill=0)
            text(16,239,self.note,7)
        return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, help='导出所有页面并退出')
    parser.add_argument('--native', action='store_true', help='原生1024×600绘图')
    parser.add_argument('--rgb565', action='store_true', help='原生 RGB565 DDR 显示预览')
    args = parser.parse_args()
    model = LcdDemo(native=args.native,rgb565=args.rgb565)
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)
        variants = [('TX', None), ('RX', None), ('IO', None)] + [('BJT', m) for m in ('输入', '输出', 'β', '交流','Early','Rin')]
        for index, (page, mode) in enumerate(variants):
            model.action(page)
            if mode: model.mode = mode
            model.action('single')
            image = model.render()
            if args.rgb565:
                image.save(args.export/f'{index}_{page}.png')
                (args.export/f'{index}_{page}.rgb565').write_bytes(frame_pixels(image))
                continue
            words = image_words(image)
            decoded = unpack_words(words,native=args.native)
            assert decoded.tobytes() == image.tobytes()
            decoded.resize((1024, 600), resample=0).save(args.export/f'{index}_{page}.png')
            (args.export/f'{index}_{page}.mem').write_text('\n'.join(f'{w:08x}' for w in words)+'\n')
        print(args.export.resolve())
        return
    import tkinter as tk
    from PIL import ImageTk
    import sys
    if sys.platform=='win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except OSError:pass
    root = tk.Tk()
    root.title('LCD 离线预览 · '+('1024×600 RGB565' if args.rgb565 else '原生1024×600' if model.native else '512×300放大'))
    root.resizable(False, False)
    canvas = tk.Canvas(root, width=1024, height=600, highlightthickness=0)
    canvas.pack()
    item = canvas.create_image(0, 0, anchor='nw')
    def refresh():
        canvas.image = ImageTk.PhotoImage(model.render().resize((1024, 600), resample=0))
        canvas.itemconfigure(item, image=canvas.image)
    def click(event):
        model.touch(event.x, event.y)
        refresh()
    def tick():
        if model.running and model.page=='RX':
            model.phase += .18
            refresh()
        root.after(150, tick)
    canvas.bind('<Button-1>', click)
    refresh(); tick()
    root.mainloop()


if __name__ == '__main__': main()
