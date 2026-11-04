# 三极管参数测量系统

基于 Zynq-7020、自制 ADDA 底板和 BJT 测试板，测量 NPN/PNP 三极管的输入、输出、电流增益和交流特性，支持大功率器件脉冲测量。

## 工程目录

| 目录 | 内容与用途 |
| --- | --- |
| src/ | FPGA 逻辑、板端驱动和上位机源码 |
| sim/ | RTL 仿真和软件测试 |
| build/ | 构建脚本、依赖清单、时序与资源报告 |
| board/ | 位流、上板脚本、安装包和实测输出 |
| data/ | 校准表和器件手册 |
| skill/ | 可复用方法、校验脚本和记录模板 |
| report/ | 设计报告、开发记录和验证结果 |

## 运行上位机

下载并解压仓库，在 Windows x64 上双击 `board/launch.cmd`。首次启动会自动还原运行库，测量结果保存到 `measurements/`。

板端使用 PYNQ 2.7，默认地址 `192.168.0.4`、用户名 `xilinx`，密码在连接时输入。安装与位流加载见 [板端运行说明](board/README.md)。

BJT 和电压测量使用 ADC 50 MHz；原始采样与频谱支持 62.5 MHz；DAC 时钟为 125 MHz。

## 源码运行与构建

电脑端使用 Python 3.13，在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r build/desktop_requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -r build/instrument_requirements.txt
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,serial]"
.\.venv\Scripts\python.exe build/restore_archives.py
.\.venv\Scripts\python.exe -m zynq_bjt.desktop --workspace measurements
```

`restore_archives.py` 还原运行库、手册及实验数据，并检查 SHA256；加 `--group datasheets` 可只还原手册。

FPGA 使用 Vivado 2026.1，器件为 `xc7z020clg400-2`：

```powershell
.\build\rebuild_fpga.ps1 -Vivado "D:\FPGA\Xilix\2026.1\Vivado\bin\vivado.bat"
.\.venv\Scripts\python.exe build/build_desktop.py
```

FPGA 构建输出在 `build/work/rebuild_adc625/`，Windows 程序在 `build/dist/desktop/`。配套 bit/HWH 位于 `board/overlay/`；源码中的显示模块修订及版本说明见 [工程说明](report/design_report.md)。

## 检查工程

```powershell
.\.venv\Scripts\python.exe build/verify_package.py
.\.venv\Scripts\python.exe skill/pynq-overlay-audit/scripts/check_bundle.py board/overlay/manifest.json
$env:PYTHONPATH="$PWD/src/python"
.\.venv\Scripts\python.exe -m unittest discover -s sim -p "test_*.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s src/python/tests -p "test_*.py" -v
```

## 材料入口

- [设计报告](report/design_report.docx)：设计原理、实现与实验结果。
- [提交材料索引](report/submission_checklist.md)：各项材料的位置。
- [实测索引](report/measurement_index.json)：24 组器件测量记录。
- [验证记录](report/package_validation.json)：软件、RTL 和程序一致性检查。
- [技能包](skill/README.md)：9 项可复用方法。

原始数据按 [归档索引](report/archive_index.json) 查找。开发过程记录位于 `report/ai_collaboration.jsonl`，包含摘要及部分原文。

项目代码采用 [MIT 许可](license.txt)，第三方资源见 [来源说明](report/source_provenance.md)。
