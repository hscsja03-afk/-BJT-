# 板端运行说明

硬件为 Zynq-7020（xc7z020clg400-2）核心板、自制 ADDA 底板和 BJT 测试板。板端使用 PYNQ 2.7 / Python 3.8，PS 配置对应本板的 DDR、eMMC、以太网和 MIO。

## 安装与启动

1. 退出占用板卡的上位机会话，关闭输出，备份现有 bit/HWH。
2. 将 `board/overlay/bjt.bit` 与 `bjt.hwh` 复制到板端 `/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/`，按 `board/overlay/manifest.json` 核对哈希。
3. 将 `board/load_overlay.py` 和 `board/zynq_bjt-0.2.0-py3-none-any.whl` 复制到板端，在同一目录执行：

```bash
python -m pip install --no-deps zynq_bjt-0.2.0-py3-none-any.whl
sudo -E python load_overlay.py --bitfile /home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit
```

使用已安装 PYNQ 的同一个 Python 环境。加载脚本配置 FPGA，并将输出初始化为关闭状态。

4. 在 Windows 双击 `board/launch.cmd`，填写连接信息，执行初始化与数字自检，再确认接线和器件档位。连接时自动部署配套代理和数据。
5. 测量结束后停止输出并断开连接。结果保存在电脑端 `measurements/`。

## 配套版本

ADC 默认 50 MHz，DAC 为 125 MHz。正式位流哈希前缀为 `d844e70d6bb3`，完整哈希见 `board/overlay/manifest.json`。

正式实现报告位于 `build/work/adc625_mmcm_20261102/`。LCD DDR 扩展的源码、实现报告和切回正式位流的记录保存在对应实验归档中，还原后查看 `report/lcd_ddr_20261103/release_status.json`。

`baremetal/` 和诊断脚本用于启动、DDR、接口等问题的定位与实验复现。更换板卡时按目标硬件调整 MIO、引脚、电平和存储配置。
