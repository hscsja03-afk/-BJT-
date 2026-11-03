---
name: register-to-analog-debug
description: 寄存器回读正常但输出异常；需要在实物照片上定位芯片或测点。
---

# 寄存器到模拟输出定位

形式：校验脚本、踩坑流程

## 适用场景

寄存器回读正常但输出异常；需要在实物照片上定位芯片或测点。

## 使用方法

先固定接线、负载和仪表设置，分开记录软件缓存、总线提交、器件回读和模拟输出。比较单次/多次 DATA 写入、启停和旧/新 PL。定位实物时按原理图确认通道、网络、位号和型号，再查 PCB 坐标，用可见锚点对应照片。

输出按[实验记录模板](../templates/experiment_record.md)填写输入、步骤、结果与复用条件。

## 协作提示词

> 请依据[同版本原理图、PCB、原照片]列出通道、网络、位号和型号；圈出实际芯片。遮挡部位标明层面，以引脚和周边器件复核指向。

方括号由使用者替换为目标项目资料。

## 已验证效果

TX1 单次提交修正有 14 项示波器检查和独立冷启动复验；EPRO 定位脚本通过 U99 合成用例、缺失位号和多 PCB 选择测试，并查得原工程 U7 坐标。

## 经验来源

停用期间重复写 DATA 时出现回读正确而输出异常；图片标签曾误指 TX1 SMA，查询原理图和 PCB 后改指 U7。

## 失效条件与处理

初始化顺序修正须由目标器件的现象支持。定位脚本读取行式 JSON EPRO，可处理一层外部 ZIP；PCB坐标与照片像素需通过方向和锚点转换。

## 独立定位脚本

```sh
python skill/register-to-analog-debug/scripts/locate_epcb.py board.zip --ref U7
python -m unittest discover -s skill/register-to-analog-debug/scripts -p "test_*.py" -v
```

依赖 Python 标准库。多个工程/PCB用 `--epro-member`、`--pcb-member` 选择。输出源文件哈希、位号、层面、原生坐标和旋转；型号对应关系从原理图确认。
