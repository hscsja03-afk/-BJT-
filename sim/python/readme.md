# 驱动、扫描、分析与界面测试

驱动、扫描、分析与界面测试。

从仓库根目录执行：

```powershell
$env:PYTHONPATH="$PWD/src/python"
python -m unittest discover -s sim/python -p "test_*.py" -v
```

## 文件

- [test_acquisition_upgrade.py](test_acquisition_upgrade.py)
- [test_baremetal.py](test_baremetal.py)
- [test_bundle.py](test_bundle.py)
- [test_capture_bulk.py](test_capture_bulk.py)
- [test_derived_analysis.py](test_derived_analysis.py)
- [test_desktop.py](test_desktop.py)
- [test_desktop_lcd.py](test_desktop_lcd.py)
- [test_desktop_output.py](test_desktop_output.py)
- [test_desktop_ui.py](test_desktop_ui.py)
- [test_driver.py](test_driver.py)
- [test_lcd.py](test_lcd.py)
- [test_lcd_framebuffer.py](test_lcd_framebuffer.py)
- [test_lcd_native.py](test_lcd_native.py)
- [test_lcd_scan_stream.py](test_lcd_scan_stream.py)
- [test_meter_ve.py](test_meter_ve.py)
- [test_mio.py](test_mio.py)
- [test_node_settling.py](test_node_settling.py)
- [test_npn_pulse_noise.py](test_npn_pulse_noise.py)
- [test_parameter_view.py](test_parameter_view.py)
- [test_pdf_view.py](test_pdf_view.py)
- [test_pnp_pulse_noise.py](test_pnp_pulse_noise.py)
- [test_point_details.py](test_point_details.py)
- [test_profiles.py](test_profiles.py)
- [test_pulse.py](test_pulse.py)
- [test_pulse_timing_ui.py](test_pulse_timing_ui.py)
- [test_result_methods.py](test_result_methods.py)
- [test_runtime.py](test_runtime.py)
- [test_scan.py](test_scan.py)
- [test_scope_display.py](test_scope_display.py)
- [test_scope_fft.py](test_scope_fft.py)
- [test_scope_workbench.py](test_scope_workbench.py)
- [test_spi.py](test_spi.py)
- [test_sweep_segments.py](test_sweep_segments.py)
- [test_tx1.py](test_tx1.py)
- [test_tx1_bus_decode.py](test_tx1_bus_decode.py)
- [test_tx3_compatibility.py](test_tx3_compatibility.py)
- [test_tx_ac_publication.py](test_tx_ac_publication.py)
- [test_waveform_metrics.py](test_waveform_metrics.py)
- [test_waveform_reference.py](test_waveform_reference.py)
- [test_workbench_november.py](test_workbench_november.py)
- [test_workbench_tools.py](test_workbench_tools.py)
