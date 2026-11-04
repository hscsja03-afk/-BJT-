---
name: pynq-overlay-audit
description: 用参数化清单核对 bit/HWH 哈希、模块实例和 AXI 地址，适用于不同 PYNQ 项目与板卡。
---

# 通用 PYNQ Overlay 校验

形式：校验脚本、排错流程

## 适用场景

换题目、换板卡或换 Vivado 构建时核对 bit/HWH、模块实例和地址。

## 本队题目之外的应用场景

可用于PYNQ 图像处理加速器、数据采集卡、电机控制外设。

迁移方法：替换 bit/HWH、外设实例名、地址窗口和文件哈希；校验脚本通过清单读取这些参数，不依赖 BJT 寄存器或通道名。

可复用的输出：文件配对、地址匹配和哈希检查结果。

## 使用方法

准备同名 bit/HWH 与 JSON 清单，填入文件 SHA256、目标实例、base 和 size。运行下方脚本；核对 PS 初始化、MIO 和电压后，在目标板检查外设 ID、版本及超时行为。

输出按[实验记录模板](../templates/experiment_record.md)填写输入、步骤、结果与复用条件。

## 协作提示词

> 请根据[bit/HWH、板卡版本、PS配置、寄存器契约]核对文件和地址；给出可重复的检查命令，分开记录文件检查、数字自检和模拟测量。

方括号由使用者替换为目标项目资料。

## 已验证效果

文件哈希、模块实例和地址校验；合成异名实例通过，错误地址与文件篡改触发拒绝。

## 经验来源

早期只迁移 PL 文件，PS/DDR 配置没有随板卡匹配；物理通道名与 ADC A/B 顺序不同。

## 失效条件与处理

文件检查适用于包含 MODULE/MEMRANGE 的 HWH。更换元数据格式时先检查解析器；板上运行另需匹配 DDR、MIO、电压和时钟。

## 独立运行

依赖 Python 标准库。

```sh
python skill/pynq-overlay-audit/scripts/check_bundle.py --example
python skill/pynq-overlay-audit/scripts/check_bundle.py path/to/manifest.json
python -m unittest discover -s skill/pynq-overlay-audit/scripts -p "test_*.py" -v
```

清单路径相对于清单自身。填写目标实例和地址，使同一检查器可用于不同外设和板卡。测试采用合成配置；目标板的电气及运行条件按上文核对。
