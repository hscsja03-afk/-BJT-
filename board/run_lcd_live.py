"""使用当前上位机配套代理和已运行的生产位流，不切换Overlay。"""
import argparse,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def release_base():
 launcher=(ROOT/'LaunchDesktop.cmd').read_text(encoding='utf-8-sig')
 match=re.search(r'%~dp0([^"\r\n]+ZynqBjtDesktop\.exe)',launcher,re.I)
 if not match:raise RuntimeError('无法识别当前上位机入口')
 base=(ROOT/match.group(1)).parent/'_internal'
 if not (base/'agent.pyz').is_file():raise RuntimeError('当前发行缺少板端代理')
 return base


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--seconds',type=float,default=0)
 args=parser.parse_args()
 base=release_base()
 out=ROOT/'report/lcd_update_20261102'/time.strftime('live_%Y%m%d_%H%M%S')
 out.mkdir(parents=True,exist_ok=False)
 print('LCD 使用当前生产位流；请先断开上位机板卡会话。',flush=True)
 child=subprocess.Popen([sys.executable,str(ROOT/'board/lcd_live.py'),
     '--base',str(base),'--seconds',str(args.seconds),'--report',str(out/'session.json')],cwd=ROOT)
 try:return child.wait()
 except KeyboardInterrupt:return child.wait(timeout=45)


if __name__=='__main__':raise SystemExit(main())
