# ADC、DAC 与三极管实测比对

索引包含 24 组三极管扫描，仪器记录包含 ADC 直流采集与 TX2/TX3 波形比对。原始数据由索引中的路径和 SHA256 定位。

从仓库根目录执行：

```powershell
python build/checks/summarize_results.py
python build/checks/summarize_results.py --plots
```

| 目录 | 内容 |
| --- | --- |
| [comparison/](comparison/) | ADC、DAC 与三极管扫描比对表 |
| [instruments/](instruments/) | 仪器读数与波形来源 |

## 文件

- [run_index.json](run_index.json)
