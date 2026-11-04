# 提交材料索引

| 材料 | 用途 | 位置 |
| --- | --- | --- |
| 源码 | FPGA、板端和上位机实现 | src/ |
| 仿真与测试 | 检查功能与软件行为 | sim/、report/validation/ |
| 构建与实现报告 | 复现工程，查看时序和资源占用 | build/ |
| 硬件设计 | ADDA 底板和 BJT 测试板的原理图、PCB、网表与可编辑工程 | board/hardware/ |
| 上板文件 | 安装、加载位流和运行设备 | board/ |
| 实测数据 | 查看器件测点与运行记录 | report/measurement_index.json |
| 校准与参考数据 | 电压电流换算及结果对照 | data/ |
| 技能包 | 复用校验和排错方法 | skill/readme.md |
| 设计报告 | 原理、架构、优化与实验结果 | [PDF](design_report.pdf) |
| 工程说明 | 源码结构、接口和版本配置 | report/design_report.md |
| 协作记录 | 关键问题、方案取舍与工程心得 | report/ai_collaboration.md |
| 数据归档索引 | 定位批量实验资料 | report/archive_index.json |
| 许可与来源 | 代码授权和第三方资源说明 | license.txt、report/source_provenance.md |

运行 `python build/restore_archives.py` 还原归档。协作记录采用 Markdown，按四个工程案例组织。
