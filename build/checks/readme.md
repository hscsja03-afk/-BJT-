# 工程校验、归档读取与测量汇总

工程校验、归档读取与测量汇总。

从仓库根目录执行：

```powershell
python build/checks/verify_package.py
python build/checks/restore_archives.py
python build/checks/summarize_results.py --plots
```

## 文件

- [audit_distribution.py](audit_distribution.py)
- [check_overlay.py](check_overlay.py)
- [restore_archives.py](restore_archives.py)
- [summarize_results.py](summarize_results.py)
- [verify_package.py](verify_package.py)
