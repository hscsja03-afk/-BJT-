# 构建脚本、依赖与实现报告

构建脚本、依赖与实现报告。

从仓库根目录执行：

```powershell
.\build\setup.ps1
.\build\test.ps1
.\build\build_software.ps1
.\build\rebuild_fpga.ps1 -Vivado "C:\AMD\2026.1\Vivado\bin\vivado.bat"
```

| 目录 | 内容 |
| --- | --- |
| [checks/](checks/) | 工程校验、归档读取与测量汇总 |
| [environment/](environment/) | Python 环境与仪器依赖 |
| [fpga/](fpga/) | FPGA 工程创建与时序检查 |
| [reports/](reports/) | FPGA 各版本资源与时序报告 |
| [software/](software/) | 上位机打包与 Notebook 生成 |

## 文件

- [archive_manifest.json](archive_manifest.json)
- [build_software.ps1](build_software.ps1)
- [rebuild_fpga.ps1](rebuild_fpga.ps1)
- [setup.ps1](setup.ps1)
- [test.ps1](test.ps1)
