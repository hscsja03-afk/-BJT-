# Early 参数与输入电阻

输出曲线按固定 IB 分组，对 UCE/UEC ≥ 1 V 的线性尾段拟合 IC(mA)=k×U+b。横轴截距为 -VA=-b/k，等效小信号输出电阻 ro(Ω)=1000/k。R²≥0.9 且斜率至少为标准误差三倍的拟合进入汇总，拟合点、区间和统计量保存在附加 CSV 中。

交流输入电阻采用同相幅度近似：

IB_peak=(Vin_peak−VB_peak)/Rtest

Rin=Rtest×VB_peak/(Vin_peak−VB_peak)

计算检查正分母。Rtest 默认 100 Ω，可在交流换算页修改；电阻、缓冲增益和反馈比例随 run.json 保存。Rin 为上述条件下的等效输入电阻估算。

PNP 历史 Rin 和电流增益按同一记录 ID 显示；当次采样结果单独保存。derived_analysis 目录包含图形、分析 JSON 和 Early 参数表。

数据手册参数表支持单位、条件及页码定位。长晶 2N5401 的 18 条内置参数按原 PDF 第 1、2 页建立审核数据，匹配原文件 SHA256 和数字列；JSON 同时保留自动提取候选。
