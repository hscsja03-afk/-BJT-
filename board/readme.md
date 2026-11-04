# 板端运行说明

硬件为 Zynq-7020（xc7z020clg400-2）核心板、自制 ADDA 底板和 BJT 测试板。板端使用 PYNQ 2.7 / Python 3.8，PS 配置对应本板的 DDR、eMMC、以太网和 MIO。

两套板卡的原理图、PCB、网表和可编辑工程见 [硬件设计资料](hardware/readme.md)。

## 目录

| 目录 | 内容 |
| --- | --- |
| [hardware/](hardware/) | ADDA 与 BJT 原理图、PCB 及硬件工程 |
| [overlay/](overlay/) | FPGA 位流、硬件描述与地址配置 |
| [software/](software/) | 板端 Python 安装包 |
| [desktop/](desktop/) | 上位机运行库与操作说明 |
| [notebooks/](notebooks/) | PYNQ 交互测量示例 |
| [config/](config/) | PS 配置与 OCM 链接脚本 |
| [boot/](boot/) | Zynq 启动、JTAG 与系统检查 |
| [connection/](connection/) | SSH、串口与设备连接 |
| [startup/](startup/) | 板端代理与开机启动 |
| [storage/](storage/) | QSPI 与 eMMC 映像工具 |
| [calibration/](calibration/) | ADC 与 DAC 校准工具 |
| [diagnostics/](diagnostics/) | 采样、输出、DDR 与器件诊断 |
| [instruments/](instruments/) | 示波器通信与波形测量 |
| [lcd/](lcd/) | LCD 显示、帧缓冲与设备控制 |
| [analysis/](analysis/) | 测量记录分析与图表导出 |
| [results/](results/) | 三极管实测记录与曲线数据 |
| [baremetal/](baremetal/) | 裸机程序与启动映像 |
| [tx1_isolation/](tx1_isolation/) | TX1 总线隔离实验文件 |

## 安装与启动

1. 退出占用板卡的上位机会话，关闭输出，备份现有 bit/HWH。
2. 将 `board/overlay/bjt.bit` 与 `bjt.hwh` 复制到板端 `/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/`，按 `board/overlay/manifest.json` 核对哈希。
3. 将 `board/load_overlay.py` 和 `board/software/zynq_bjt-0.2.0-py3-none-any.whl` 复制到板端，在同一目录执行：

```bash
python -m pip install --no-deps zynq_bjt-0.2.0-py3-none-any.whl
sudo -E python load_overlay.py --bitfile /home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit
```

使用已安装 PYNQ 的同一个 Python 环境。加载脚本配置 FPGA，并将输出初始化为关闭状态。

4. 在 Windows 双击 `board/launch.cmd`，填写连接信息，执行初始化与数字自检，再确认接线和器件档位。连接时自动部署配套代理和数据。
5. 测量结束后停止输出并断开连接。结果保存在电脑端 `measurements/`。

## 配套版本

ADC 默认 50 MHz，DAC 为 125 MHz。正式位流哈希前缀为 `d844e70d6bb3`，完整哈希见 `board/overlay/manifest.json`。

| 位流目录 | 功能与配套报告 |
| --- | --- |
| `board/overlay/` | ADC 50/62.5 MHz、DAC 125 MHz；实测与校准记录对应版本，报告位于 `build/reports/adc625_mmcm_20261102/` |
| `board/overlay/build_20261104/` | 2026-11-04 源码构建，含 LCD DDR 显示逻辑；资源、时序、DRC 与构建身份见 `build/reports/lcd_ddr_20261104/` |

每个目录的 `manifest.json` 记录对应 bit/HWH 的哈希。测量记录和校准表保存采集时的位流身份与采样条件。

`baremetal/` 和诊断脚本用于启动、DDR、接口等问题的定位与实验复现。更换板卡时按目标硬件调整 MIO、引脚、电平和存储配置。
