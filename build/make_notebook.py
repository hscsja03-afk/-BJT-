"""Rebuild the checked-in notebook from explicit cells (no hardware execution)."""
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
def cell(kind, source):
    result = {'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code': result.update(execution_count=None, outputs=[])
    return result

cells = [
cell('markdown', '''# Zynq-7020 晶体管参数扫描\n
界面包含 NPN 输入、输出/Early、输出 β线性精度和交流 fβ/fT 四种测量。默认使用离线模拟；模拟结果不是实测数据，IB 是 TX1 标称设定值换算的估算值。\n
输出 β线性精度固定 UCE≈5 V，扫描 TX1 并以 2 kΩ 估算 IB；仅用 UCE>1 V 且 IC>0 的放大区点，以 IC=(VCC反馈-VC反馈)/100 Ω 计算 IC；舍弃前两组，按旧源做相邻两点平均后拟合 IC-IB。交流按旧源用输入端×10采样、50 Ω 输入电阻和 100 Ω 输出电阻计算 β(f)，fβ 取 Au 的 0.707 倍截止点，fT=Au×fβ。TX1=0.2 V、TX2=1.5 V控制量（6倍约得9 V VCC）、77/48=00；受本板波形校准范围限制，旧源的52 mVpp方波改用TX3 50 mVpp正弦。RX2/VCC比例0.4及交流83/85状态待确认。实板扫描须确认测试板与安全负载已接。\n
输出特性和 β 线性扫描使用用户确认的 ADC1/RX1=VC、ADC2/RX2=VCC。交流扫频使用用户确认的 ADC1/RX1=集电极输出、ADC2/RX2=基极交流输入，TX3 注入交流，TX2 提供固定 VCC。\n
实板流程须先完成本板 Linux/PYNQ 启动、数字自检和迁移后的模拟校准复核。打开 Notebook 不会下载位流或自动启用输出；每次扫描开始前要求 TX1/TX2/TX3 均静音。\n
测量会保存逐点 CSV、原始 ADC 帧或统计窗及包含配置/校准哈希的运行记录。'''),
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
选择测量页并调整测量参数。离线模拟不导入 PYNQ，也不枚举或打开真实设备；实板扫描在当前位流和前端校准完成资格验证前会被拒绝。'''),
cell('code', '''app = NpnNotebook(calibration, frontend, output_root=root / "report/notebook_runs")
app.display()
'''),
cell('markdown', '''## 实板入口（完成启动与校准后使用）\n
先核对当前安装的是自制 ADDA 底板及成对的 bit/HWH。下面仅给出明确步骤，代码处于注释状态；打开此 Notebook 不会下载位流。\n
`qualification.json` 必须来自本次迁移后实际复核的记录，绑定 bit/HWH 哈希、三个校准文件哈希、前端配置及采样率。旧档案不能自动成为新版本的已验证记录。'''),
cell('code', '''# from zynq_bjt.runtime import Board
# import json
# board = Board.from_pynq(root / "board/overlays/qualified/bjt.bit", program=True)
# identity = board.initialize(adc_divider=20, dac_divider=20)
# qualification = json.loads((root / "data/qualification.json").read_text(encoding="utf-8"))
# hardware_app = NpnNotebook(calibration, frontend, board=board,
#     qualification=qualification, output_root=root / "data/hardware_runs")
# hardware_app.display()
'''),
cell('markdown', '''## 结束实验\n
先等待扫描结束或点击停止，确认运行记录中的清理结果，再关闭实板会话。关闭会话会尝试停止本会话控制的输出并释放 GPIO；清理失败必须保留为错误，不能声称输出已停止。'''),
cell('code', '''# 扫描工作线程结束后，按实际建立的会话执行：
# board.close()
''')]
notebook = {'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
            'language_info': {'name': 'python', 'version': '3.8'}}, 'nbformat': 4, 'nbformat_minor': 5}
for i, item in enumerate(cells): item['id'] = f'bjt-{i:02d}'
cells[0]['source'] = [
    line.replace('RX2/VCC比例0.4及交流83/85状态待确认。',
                 '输出和β线性页必须填写实测VCC反馈比例（ADC端电压/VCC），不再预置旧资料的0.4；交流继电器按确认值83=0、85=1。')
    for line in cells[0]['source']]
out = root/'board/notebooks/npn_input.ipynb'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding='utf-8')
print(out)
