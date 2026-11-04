# 工程验证与测试结果

## 验证方法

RTL 仿真通过测试台驱动接口、比较期望值和寄存器读回值，检查 AXI 写通道时序、ADC 缓冲读写和 LCD DDR 读出。软件测试覆盖寄存器操作、扫描流程、参数校验、输出关闭、数据保存和图形显示；程序运行检查覆盖安装包资源、测量流程和结果导出。仪器测试通过信号发生器和示波器采集端口数据，保留设定值、读数、原始采样及逐点误差。

| 验证项目 | 结果 | 记录 |
| --- | --- | --- |
| 软件回归 | 312 项通过 | `sim/results/software_tests.log` |
| 分析与特性计算 | 14 项通过，2 项可选 Notebook 控件测试跳过 | 同上 |
| 裸机 C 驱动 | 8 类故障处理测试及时间基准测试通过 | `sim/results/c_driver_tests.log` |
| AXI 寄存器接口 | 测试台通过 | `sim/results/rtl_axi.log` |
| ADC 缓冲深度 | 测试台通过 | `sim/results/rtl_adc_depth.log` |
| LCD DDR 读取 | 测试台通过 | `sim/results/rtl_lcd_ddr.log` |
| 软件构建与运行 | Python 安装包、Windows 程序构建及程序运行检查通过 | `sim/results/software_build.log`、`sim/results/program_runtime.json` |

软件扫描测试使用模拟输入，实测附件中的扫描记录使用板卡采样。记录中的 `simulated` 字段标识数据类别。

## 综合与实现

器件：xc7z020clg400-2；工具：Vivado 2026.1；构建日期：2026-11-04。该构建包含 LCD DDR 显示逻辑，配套 bit/HWH 及校验清单位于 `board/overlay/build_20261104/`。

| 指标 | 数值 |
| --- | --- |
| Slice LUT | 3,889 / 53,200（7.31%） |
| Slice 寄存器 | 3,184 / 106,400（2.99%） |
| Block RAM Tile | 123 / 140（87.86%） |
| DSP | 2 / 220（0.91%） |
| Bonded IOB | 117 / 125（93.60%） |
| BUFGCTRL | 8 / 32（25.00%） |
| AXI 总线时钟 | 50 MHz |
| ADC 构建约束 | 62.5 MHz |
| BJT 测量初始化采样率 | 50 MSPS |
| DAC 时钟 | 125 MHz |
| 建立时间最差裕量 WNS | 0.394 ns |
| 保持时间最差裕量 WHS | 0.035 ns |
| TNS / THS | 0 / 0 ns |
| 位流生成 DRC | 0 错误 |

综合资源报告为 `build/reports/lcd_ddr_20261104/synthesis_utilization.rpt`，实现资源报告为 `utilization.rpt`。`timing_summary.rpt`、`drc.rpt`、`cdc.rpt`、`bus_skew.rpt` 和 `io.rpt` 分别记录时序、设计规则、跨时钟域、总线偏斜及引脚配置。器件、工具版本、源码摘要和 bit/HWH 摘要见 `build_identity.json`。

## 实测输出与仪器比对

`board/results/` 收录 24 组实测记录，覆盖 NPN/PNP 小功率与大功率档位的输入、输出、交流、β 和极性识别，以及大功率脉冲扫描。每组保留测点 CSV、采集配置、板卡标识和测量时间；曲线图直接由对应 CSV 生成。

| 仪器比对项目 | 结果 |
| --- | --- |
| RX1 DC 独立验证 | 19 点，最大绝对差 0.338 mV |
| RX2 DC 独立验证 | 19 点，最大绝对差 0.394 mV |
| DC 比对条件 | DG1032Z，High-Z，50 MSPS，验证限值 5 mV |
| TX2/TX3 示波器比对 | 77 条记录，幅值判据通过 77 条，偏置判据通过 63 条 |
| 最大幅值绝对差 | 3.002 mV |
| 示波器 | Rigol DS1104Z，接线与探头设置见采集记录 |

DC 比对基准为发生器设定值。波形幅值按各波形记录的测量方法计算，逐点的幅值误差、偏置误差及采集程序判定保存在 `data/measurements/comparison/dac_scope.csv`。幅值与偏置分别统计；示波器读数、原始波形路径与 SHA256 见 `data/measurements/instruments/tx/verification.json`；ADC 采集记录位于 `report/rx1_generator_nominal_20261030/` 和 `report/rx2_generator_nominal_20261031/`。

## 文件与采集标识

| 记录 | 日期 | 位流 SHA256 |
| --- | --- | --- |
| FPGA 构建产物 | 2026-11-04 | `102d7445edd24724b080899e34809a780e64e5203b3365f14852e9f8ce32d888` |
| 示波器比对记录 | 2026-11-03 | `d844e70d6bb3a813ab08eedd0cf181cbffe8774fe22cac0b4dadf0089bd54001` |

实测记录按采集时的位流、采样率和接线配置使用。三极管扫描的标识见 `data/measurements/run_index.json`，ADC 标识见对应采集目录中的 `collection.json`。`build/checks/summarize_results.py` 从数据归档读取采样文件，检查摘要并计算比对表；加 `--plots` 可生成实测曲线图。

## 复现命令

```powershell
.\build\setup.ps1
.\build\test.ps1
.\.venv\Scripts\python.exe build/checks/summarize_results.py
.\.venv\Scripts\python.exe build/checks/summarize_results.py --plots
```

比对表输出到 `data/measurements/comparison/`，指标汇总为 `report/measurements/summary.json`，曲线图输出到 `measurements/summary_plots/`。RTL 仿真可通过 `build/test.ps1 -Vivado <vivado.bat>` 执行。
