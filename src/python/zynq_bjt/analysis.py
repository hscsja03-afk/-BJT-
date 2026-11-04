"""BJT output, Early-voltage and beta-linearity analysis helpers."""
import math
import statistics

BETA_ACTIVE_UCE_MIN_V = 1.0


def collector_current_a(vcc_v, vc_v, resistor_ohm=100.0):
    values = (vcc_v, vc_v, resistor_ohm)
    if any(not math.isfinite(value) for value in values) or resistor_ohm <= 0:
        raise ValueError("Output voltages and collector resistor must be finite")
    return (vcc_v - vc_v) / resistor_ohm


def pick_at_target_uce(points, target_v=5.0, max_error_v=0.5,
                       minimum_active_uce_v=BETA_ACTIVE_UCE_MIN_V):
    """Interpolate Ic at target UCE, falling back to the nearest point."""
    if not math.isfinite(minimum_active_uce_v):
        raise ValueError("Minimum active-region UCE must be finite")
    values = sorted((float(p["uce_v"]), float(p["ic_a"])) for p in points
                    if math.isfinite(float(p["uce_v"])) and math.isfinite(float(p["ic_a"]))
                    and float(p["uce_v"]) > minimum_active_uce_v and float(p["ic_a"]) > 0)
    if not values:
        return None
    merged = []
    for uce, ic in values:
        if merged and abs(uce - merged[-1][0]) <= 1e-9:
            prior_uce, currents = merged[-1]
            currents.append(ic)
        else:
            merged.append((uce, [ic]))
    values = [(uce, statistics.fmean(currents)) for uce, currents in merged]
    for (low_uce, low_ic), (high_uce, high_ic) in zip(values, values[1:]):
        if low_uce <= target_v <= high_uce and high_uce > low_uce:
            fraction = (target_v - low_uce) / (high_uce - low_uce)
            return {"uce_v": target_v, "ic_a": low_ic + fraction * (high_ic - low_ic),
                    "method": "interpolated", "error_v": 0.0}
    uce, ic = min(values, key=lambda item: abs(item[0] - target_v))
    error = abs(uce - target_v)
    if error > max_error_v:
        return None
    return {"uce_v": uce, "ic_a": ic, "method": "nearest", "error_v": error}


def fit_early_voltage(points, minimum_start_uce_v=1.0):
    """Fit candidate high-UCE tails as in the NPN small-power source script."""
    values = sorted((float(p["uce_v"]), float(p["ic_a"]) * 1000.0) for p in points
                    if math.isfinite(float(p["uce_v"])) and math.isfinite(float(p["ic_a"]))
                    and float(p["uce_v"]) >= 0 and float(p["ic_a"]) > 0)
    if len(values) < 8:
        return None
    active = [(x, y) for x, y in values if x >= minimum_start_uce_v]
    if len(active) < 8 or active[-1][0] <= active[0][0]:
        return None
    min_points = max(8, int(math.ceil(len(active) * 0.20)))
    span = active[-1][0] - active[0][0]
    candidates = []
    for step in range(9):
        start = active[0][0] + (0.30 + step * 0.05) * span
        fit = [(x, y) for x, y in active if x >= start]
        if len(fit) < min_points:
            continue
        slope, intercept, r_squared = _linear_fit([p[0] for p in fit], [p[1] for p in fit])
        if slope > 0 and intercept > 0:
            x_mean=statistics.fmean(p[0] for p in fit)
            sxx=sum((p[0]-x_mean)**2 for p in fit)
            residual=sum((y-slope*x-intercept)**2 for x,y in fit)
            slope_se=math.sqrt(residual/(len(fit)-2)/sxx) if sxx>0 else float('inf')
            uq=statistics.fmean(p[0] for p in fit)
            candidates.append({"slope_mA_per_v": slope, "intercept_mA": intercept,
                               "fit_start_uce_v": fit[0][0], "r_squared": r_squared,
                               "fit_stop_uce_v":fit[-1][0], "x_intercept_v":-intercept/slope,
                               "ro_ohm":1000.0/slope, "rce_ohm":1000.0/slope,
                               "q_uce_v":uq,"q_ic_a":(slope*uq+intercept)/1000.0,
                               "slope_standard_error_mA_per_v":slope_se,
                               "fit_reliable":r_squared>=.9 and slope>=3*slope_se,
                               "point_count": len(fit),
                               "early_va_v": abs(-intercept / slope)})
    if not candidates:
        return None
    best_r2 = max(item["r_squared"] for item in candidates)
    near_best = [item for item in candidates if item["r_squared"] >= best_r2 - 0.001]
    return min(near_best, key=lambda item: item["fit_start_uce_v"])


def input_resistance_summary(points, passband_stop_hz=150000):
    values=[];passband=[]
    for point in points:
        try:f=float(point['actual_freq_hz']);r=float(point['input_resistance_ohm'])
        except (ValueError,TypeError,KeyError):continue
        if not math.isfinite(f+r) or f<=0 or r<=0:continue
        values.append(r)
        if f<=passband_stop_hz:passband.append(r)
    return dict(point_count=len(values),minimum_ohm=min(values) if values else None,
                maximum_ohm=max(values) if values else None,
                passband_median_ohm=statistics.median(passband) if passband else None,
                equation='Rin = Rtest * VB_peak / (Vin_peak - VB_peak)',
                basis='amplitude_ratio_in_phase_assumption; excludes series test resistor; not complex impedance')


def analyze_beta_linearity(points, base_resistance_ohm=2000.0, drop_initial=2,
                           moving_average_window=2):
    """Report Ic-Ib linearity and beta spread for fixed-UCE points."""
    if not math.isfinite(base_resistance_ohm) or base_resistance_ohm <= 0:
        raise ValueError("Base resistance must be finite and positive")
    if type(drop_initial) is not int or drop_initial < 0:
        raise ValueError("drop_initial must be a nonnegative integer")
    if type(moving_average_window) is not int or moving_average_window < 1:
        raise ValueError("Moving-average window must be a positive integer")
    selected = points[drop_initial:]
    rows = [(float(p["tx1_v"]) / base_resistance_ohm, float(p["ic_a"])) for p in selected
            if math.isfinite(float(p["tx1_v"])) and math.isfinite(float(p["ic_a"]))
            and float(p["ic_a"]) > 0 and float(p['tx1_v']) > 0]
    if len(rows) < 2:
        raise ValueError("At least two beta points are required after dropping the initial points")
    ib_a = [row[0] for row in rows]
    ic_a = [row[1] for row in rows]
    beta_raw = [ic / ib for ib, ic in rows if ib > 0]
    if len(beta_raw) < 2:
        raise ValueError("At least two positive base-current points are required")
    effective_window = moving_average_window if len(rows) >= moving_average_window else 1
    if effective_window > 1:
        ib_fit = _moving_average(ib_a, effective_window)
        ic_fit = _moving_average(ic_a, effective_window)
        beta_fit = _moving_average(beta_raw, effective_window)
    else:
        ib_fit, ic_fit = ib_a[:], ic_a[:]
        beta_fit = beta_raw[:]
    if len(ib_fit) < 2 or len(beta_fit) < 2:
        raise ValueError("At least two beta points are required after moving average")
    slope, intercept, r_squared, inlier_mask = _robust_line_fit(ib_fit, ic_fit)
    residuals = [abs(y - (slope * x + intercept)) for x, y in zip(ib_fit, ic_fit)]
    span = max(ic_fit) - min(ic_fit)
    if span <= max(1e-15, max(abs(v) for v in ic_fit)*1e-9):
        raise ValueError('Collector-current span is too small for a linearity metric')
    max_error = max(residuals)
    beta_mean = statistics.fmean(beta_fit)
    beta_min, beta_max = min(beta_fit), max(beta_fit)
    beta_raw_mean = statistics.fmean(beta_raw)
    beta_raw_min, beta_raw_max = min(beta_raw), max(beta_raw)
    return {
        "point_count": len(rows),
        "fit_point_count": len(ib_fit),
        "fit_slope_beta": slope,
        "fit_intercept_a": intercept,
        "linearity_error_pct": max_error / span * 100.0 if span > 0 else 0.0,
        "max_abs_fit_error_a": max_error,
        "r_squared": r_squared,
        "beta_mean": beta_mean,
        "beta_min": beta_min,
        "beta_max": beta_max,
        "beta_spread_pct": ((beta_max - beta_min) / beta_mean * 100.0
                            if beta_mean else 0.0),
        "beta_raw_mean": beta_raw_mean,
        "beta_raw_min": beta_raw_min,
        "beta_raw_max": beta_raw_max,
        "beta_raw_spread_pct": ((beta_raw_max - beta_raw_min) / beta_raw_mean * 100.0
                                 if beta_raw_mean else 0.0),
        "base_resistance_ohm": base_resistance_ohm,
        "dropped_initial_points": drop_initial,
        "moving_average_window": effective_window,
        "fit_inlier_mask": inlier_mask,
    }


def fit_ac_response(points, passband_stop_hz=150000.0):
    """Robustly fit the legacy generalized low-pass model in log space."""
    selected = [(float(point["actual_freq_hz"]), float(point["gain"])) for point in points
                if math.isfinite(float(point["actual_freq_hz"]))
                and math.isfinite(float(point["gain"]))
                and float(point["actual_freq_hz"]) > 0 and float(point["gain"]) > 0]
    if len(selected) < 6:
        raise ValueError("At least six valid AC gain points are required")
    selected.sort()
    log_freq = [math.log(item[0]) for item in selected]
    log_gain = [math.log(item[1]) for item in selected]
    inliers = [True] * len(selected)
    threshold = math.log1p(0.04)
    best = None
    for _ in range(3):
        best = _fit_lowpass_grid(log_freq, log_gain, inliers, passband_stop_hz)
        residual = best["residual"]
        active = [value for value, include in zip(residual, inliers) if include]
        center = statistics.median(active)
        mad_sigma = 1.4826 * statistics.median(abs(value - center) for value in active)
        threshold = max(2.8 * mad_sigma, math.log1p(0.04))
        new_inliers = [abs(value - center) <= threshold for value in residual]
        if sum(new_inliers) < max(6, int(0.7 * len(new_inliers))):
            new_inliers = inliers
        if new_inliers == inliers:
            break
        inliers = new_inliers
    best = _fit_lowpass_grid(log_freq, log_gain, inliers, passband_stop_hz)
    au = math.exp(best["log_au"])
    f_beta = math.exp(best["log_fb"])
    order = best["order"]
    residual_ratios = [math.exp(residual) - 1.0 for residual, include in zip(best["residual"], inliers) if include]
    rmse = math.sqrt(statistics.fmean(value * value for value in residual_ratios))
    return {"au": au, "target_gain": au * 0.707, "f_beta_hz": f_beta,
            "order": order, "ft_hz": au * f_beta, "rmse_percent": rmse * 100.0,
            "inlier_count": sum(inliers), "point_count": len(inliers),
            "outlier_threshold_percent": math.expm1(threshold) * 100.0}


def _linear_fit(x_values, y_values):
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    if denominator <= 0:
        raise ValueError("Fit requires at least two distinct X values")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values)) / denominator
    intercept = y_mean - slope * x_mean
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, y_values))
    ss_total = sum((y - y_mean) ** 2 for y in y_values)
    r_squared = 1.0 - ss_res / ss_total if ss_total > 0 else 1.0
    return slope, intercept, r_squared


def _robust_line_fit(x_values, y_values):
    inliers = list(range(len(x_values)))
    slope, intercept, _ = _linear_fit(x_values, y_values)
    residuals = [y - (slope * x + intercept) for x, y in zip(x_values, y_values)]
    median = statistics.median(residuals)
    mad = statistics.median(abs(value - median) for value in residuals)
    if mad > 1e-15:
        robust_sigma = 1.4826 * mad
        inliers = [index for index, residual in enumerate(residuals)
                   if abs(residual - median) <= 2.5 * robust_sigma]
        if len(inliers) < 3:
            inliers = list(range(len(x_values)))
    if len(inliers) != len(x_values):
        slope, intercept, _ = _linear_fit([x_values[i] for i in inliers],
                                           [y_values[i] for i in inliers])
    y_mean = statistics.fmean(y_values)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, y_values))
    ss_total = sum((y - y_mean) ** 2 for y in y_values)
    r_squared = 1.0 - ss_res / ss_total if ss_total > 0 else 1.0
    inlier_mask = [index in inliers for index in range(len(x_values))]
    return slope, intercept, r_squared, inlier_mask


def _moving_average(values, window):
    return [statistics.fmean(values[index:index + window])
            for index in range(len(values) - window + 1)]


def _fit_lowpass_grid_scalar(log_freq, log_gain, inliers, passband_stop_hz):
    freq = [math.exp(value) for value in log_freq]
    log_fb_min = math.log(max(passband_stop_hz * 1.05, min(freq)))
    log_fb_max = math.log(max(max(freq) * 1.5, passband_stop_hz * 2.0))
    order_min, order_max = 0.5, 2.5
    huber_delta = math.log1p(0.04)
    best = None
    for _ in range(3):
        fb_grid = [log_fb_min + i * (log_fb_max - log_fb_min) / 80 for i in range(81)]
        order_grid = [order_min + i * (order_max - order_min) / 80 for i in range(81)]
        for order in order_grid:
            for log_fb in fb_grid:
                shape = [-0.5 * _logaddexp(0.0, 2.0 * order * (value - log_fb)) for value in log_freq]
                log_au = statistics.median([gain - response for gain, response, include
                                            in zip(log_gain, shape, inliers) if include])
                residual = [gain - (log_au + response) for gain, response in zip(log_gain, shape)]
                errors = [abs(value) for value, include in zip(residual, inliers) if include]
                loss = statistics.fmean(0.5 * value * value if value <= huber_delta
                                        else huber_delta * (value - 0.5 * huber_delta)
                                        for value in errors)
                if best is None or loss < best["loss"]:
                    best = {"loss": loss, "log_au": log_au, "log_fb": log_fb,
                            "order": order, "residual": residual}
        fb_step = (log_fb_max - log_fb_min) / 80
        order_step = (order_max - order_min) / 80
        log_fb_min, log_fb_max = best["log_fb"] - 4 * fb_step, best["log_fb"] + 4 * fb_step
        order_min = max(0.5, best["order"] - 4 * order_step)
        order_max = min(2.5, best["order"] + 4 * order_step)
    return best


def _logaddexp(left, right):
    high = max(left, right)
    return high + math.log1p(math.exp(-abs(left - right)))


def _fit_lowpass_grid(log_freq, log_gain, inliers, passband_stop_hz):
    """Same robust grid and tie ordering, vectorized when NumPy is available."""
    try: import numpy as np
    except ImportError: return _fit_lowpass_grid_scalar(log_freq,log_gain,inliers,passband_stop_hz)
    x=np.asarray(log_freq); y=np.asarray(log_gain); mask=np.asarray(inliers,dtype=bool)
    lo=math.log(max(passband_stop_hz*1.05,math.exp(min(log_freq))))
    hi=math.log(max(math.exp(max(log_freq))*1.5,passband_stop_hz*2.0))
    omin,omax=.5,2.5; delta=math.log1p(.04); best=None
    for _ in range(3):
        fb=np.linspace(lo,hi,81); orders=np.linspace(omin,omax,81)
        shape=-.5*np.logaddexp(0,2*orders[:,None,None]*(x[None,None,:]-fb[None,:,None]))
        au=np.median((y-shape)[:,:,mask],axis=2)
        residual=y-(au[:,:,None]+shape); errors=np.abs(residual[:,:,mask])
        loss=np.mean(np.where(errors<=delta,.5*errors**2,delta*(errors-.5*delta)),axis=2)
        i,j=np.unravel_index(np.argmin(loss),loss.shape)
        if best is None or float(loss[i,j])<best['loss']:
            best=dict(loss=float(loss[i,j]),log_au=float(au[i,j]),log_fb=float(fb[j]),order=float(orders[i]),residual=residual[i,j].tolist())
        fstep=(hi-lo)/80; ostep=(omax-omin)/80
        lo,hi=best['log_fb']-4*fstep,best['log_fb']+4*fstep
        omin,omax=max(.5,best['order']-4*ostep),min(2.5,best['order']+4*ostep)
    return best
