# 硬件设计资料

多功能三极管参数测量系统由 Zynq-7020 核心板、双通道高速 ADDA 底板和 BJT 测试板组成。本目录收录 ADDA 底板与 BJT 测试板的设计文件。

## 双通道高速 ADDA 底板

| 文件 | 内容 |
| --- | --- |
| [hardware_project.epro](adda/hardware_project.epro) | 可编辑工程，包含原理图与 PCB |
| [schematic.pdf](adda/schematic.pdf) | 完整原理图 |
| [netlist.tel](adda/netlist.tel) | 电路网表 |
| [pcb_3d.png](adda/pcb_3d.png) | PCB 三维预览 |
| [design_notes.xlsx](adda/design_notes.xlsx) | 设计说明表 |
| [ad9747_firmware_guide.md](adda/ad9747_firmware_guide.md) | AD9747 固件与接口说明 |
| [ad9516_config_01.png](adda/ad9516_config_01.png)、[ad9516_config_02.png](adda/ad9516_config_02.png) | AD9516-3 时钟配置图 |

## BJT 测试板

| 文件 | 内容 |
| --- | --- |
| [hardware_project.epro2](bjt/hardware_project.epro2) | 可编辑设计工程 |
| [netlist.tel](bjt/netlist.tel) | 电路网表 |
| [pcb_layout.png](bjt/pcb_layout.png) | PCB 布局预览 |
| [pcb_3d.png](bjt/pcb_3d.png) | PCB 三维预览 |
| [schematic_ac.png](bjt/schematic_ac.png) | 交流测量电路 |
| [schematic_base_current_source.png](bjt/schematic_base_current_source.png) | 基极恒流源，100 nA～40 mA |
| [schematic_power_amplifier.png](bjt/schematic_power_amplifier.png) | 供电、软启动和功放激励电路 |
| [schematic_interface.png](bjt/schematic_interface.png) | 板间接口 |
| [schematic_dual_supply.png](bjt/schematic_dual_supply.png) | 正负 5 V 供电 |
| [schematic_polarity_switch.png](bjt/schematic_polarity_switch.png) | NPN/PNP 切换电路 |
| [schematic_measurement_switch.png](bjt/schematic_measurement_switch.png) | 测量档位切换电路 |

工程文件用于编辑电路和布线，PDF 与 PNG 用于浏览。文件大小与 SHA256 见 [校验清单](manifest.json)。
