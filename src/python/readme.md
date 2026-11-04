# 测量驱动、板端代理与上位机程序

测量驱动、板端代理与上位机程序。

从仓库根目录执行：

```powershell
python -m pip install -e ".[desktop,serial]"
python -m zynq_bjt.desktop --workspace measurements
```

| 目录 | 内容 |
| --- | --- |
| [tests/](tests/) | 特性分析与测量流程测试 |
| [zynq_bjt/](zynq_bjt/) | 设备驱动、测量分析与图形界面 |
