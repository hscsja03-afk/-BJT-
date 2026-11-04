"""Rebuild the checked-in notebook from explicit cells (no hardware execution)."""
from pathlib import Path
import json

root = Path(__file__).resolve().parents[2]
def cell(kind, source):
    result = {'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code': result.update(execution_count=None, outputs=[])
    return result

cells = [
cell('markdown', '''# Zynq-7020 三极管参数扫描示例\n
提供 NPN 输入、输出/Early、β 线性精度和交流 fβ/fT 测量页面。扫描保存测点 CSV、原始 ADC 帧或统计窗，以及配置和校准身份。\n
页面初始为模拟模式，运行记录使用 `simulated` 标识数据类别。实板测量按前端接线填写 VCC 反馈比例、采样电阻和通道配置，并使用对应位流的校准记录。\n
β 线性精度按工作点电流拟合；交流扫频由采样幅值计算频率响应及特征频率。各测量条件和换算参数随运行记录保存。'''),
cell('code', '''from pathlib import Path
import sys
root = Path.cwd().resolve()
while not (root / "data/frontend.json").is_file():
    if root.parent == root:
        raise FileNotFoundError("请从工程目录或其子目录打开此 Notebook")
    root = root.parent
sys.path.insert(0, str(root / "src/python"))
from zynq_bjt import Calibration, Frontend
from zynq_bjt.notebook import NpnNotebook
calibration = Calibration(root / "data")
frontend = Frontend.load(root / "data/frontend.json")
'''),
cell('markdown', '''## 扫描界面\n
选择测量页面，设置扫描范围、步进和反馈参数。实板模式通过位流与校准身份检查后启动采集。'''),
cell('code', '''app = NpnNotebook(calibration, frontend, output_root=root / "measurements/notebook_runs")
app.display()
'''),
cell('markdown', '''## PYNQ 实板入口\n
连接 ADDA 底板与 BJT 测试板，加载成对的 bit/HWH，并执行数字自检。以下代码按顺序创建板卡与测量界面。\n
`data/qualification.json` 记录本板校准结果，绑定 bit/HWH、校准文件、前端配置及采样率；运行前按对应校准记录填写。'''),
cell('code', '''# from zynq_bjt.runtime import Board
# import json
# board = Board.from_pynq(root / "board/overlay/bjt.bit", program=True)
# identity = board.initialize(adc_divider=20, dac_divider=8)
# qualification = json.loads((root / "data/qualification.json").read_text(encoding="utf-8"))
# hardware_app = NpnNotebook(calibration, frontend, board=board,
#     qualification=qualification, output_root=root / "measurements/hardware_runs")
# hardware_app.display()
'''),
cell('markdown', '''## 结束实验\n
等待扫描结束或点击停止，再关闭板卡会话。关闭操作执行输出停止与 GPIO 释放，结果保存在运行记录中。'''),
cell('code', '''# 扫描工作线程结束后，按实际建立的会话执行：
# board.close()
''')]
notebook = {'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
            'language_info': {'name': 'python', 'version': '3.8'}}, 'nbformat': 4, 'nbformat_minor': 5}
for i, item in enumerate(cells): item['id'] = f'bjt-{i:02d}'
out = root/'board/notebooks/npn_input.ipynb'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding='utf-8')
print(out)
