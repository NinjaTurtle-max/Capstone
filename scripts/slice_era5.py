"""ERA5 (NAS, 동아시아 0.25°) → 한반도 박스 월별 netCDF.

대상 (값은 바꾸지 않고 공간만 자른다, float32·zlib)
  sl  : era5_sl_YYYYMM.nc          — blh·sp·z·t2m (단일층)
  pbl : era5_wind_YYYYMM_z100.nc   — u_pbl·v_pbl·blh·sp·t2m (NO2-Proxy-XCO2 파생 PBL풍, z_min=100 m)
  pl  : era5_pl_YYYYMM.nc          — 700–1000 hPa 10층 u·v·z (기압면)
  oro : era5_orography.nc          — 지형 지오퍼텐셜 (1회)

사용:
  python scripts/slice_era5.py --months 202001-202012 --kinds sl,pbl,pl,oro
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

KINDS = {
    "sl": (config.ERA5_PL_DIR, "era5_sl_{ym}.nc"),
    "pbl": (config.ERA5_PBL_DIR, "era5_wind_{ym}_z100.nc"),
    "pl": (config.ERA5_PL_DIR, "era5_pl_{ym}.nc"),
    "oro": (config.ERA5_PL_DIR, "era5_orography.nc"),
}


def cut(src: Path, dst: Path) -> dict:
    """박스로 자르고 원천과 한 격자점을 대조한 점검값을 돌려준다."""
    b = config.BOX
    with xr.open_dataset(src) as ds:
        la = "latitude" if "latitude" in ds.coords else "lat"
        lo = "longitude" if "longitude" in ds.coords else "lon"
        # 원천은 위도 내림차순(50→20) — 순서에 맞춰 자른다
        desc = float(ds[la][0]) > float(ds[la][-1])
        lat_sl = slice(b["lat_max"], b["lat_min"]) if desc else slice(b["lat_min"], b["lat_max"])
        sub = ds.sel({la: lat_sl, lo: slice(b["lon_min"], b["lon_max"])}).load()
        # 대조: 박스 중앙 격자점의 첫 변수 값이 원천과 같은지
        v = next(iter(sub.data_vars))
        pt = {la: float(sub[la][len(sub[la]) // 2]), lo: float(sub[lo][len(sub[lo]) // 2])}
        same = bool(np.array_equal(sub[v].sel(pt).values, ds[v].sel(pt).values, equal_nan=True))
        enc = {k: {"zlib": True, "complevel": 4, "dtype": "float32"} for k in sub.data_vars}
        tmp = dst.with_name(dst.name + ".tmp")
        sub.to_netcdf(tmp, encoding=enc)
        os.replace(tmp, dst)
        return {"dims": {k: int(n) for k, n in sub.sizes.items()}, "src_dims": {k: int(n) for k, n in ds.sizes.items()},
                "lat_range": [float(sub[la].min()), float(sub[la].max())],
                "lon_range": [float(sub[lo].min()), float(sub[lo].max())],
                "center_point_equal": same, "bytes": dst.stat().st_size}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", required=True, help="YYYYMM-YYYYMM")
    ap.add_argument("--kinds", default="sl,pbl,pl,oro")
    ap.add_argument("--min-free-gib", type=float, default=10.0, help="로컬 여유가 이 값 아래로 내려가면 중단")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    a0, a1 = a.months.split("-")
    months = [p.strftime("%Y%m") for p in pd.period_range(pd.Period(a0, "M"), pd.Period(a1, "M"), freq="M")]
    config.MANIFEST_OUT.mkdir(parents=True, exist_ok=True)
    log = config.MANIFEST_OUT / "era5.jsonl"
    for kind in a.kinds.split(","):
        src_dir, pat = KINDS[kind]
        out_dir = config.ERA5_OUT / kind
        out_dir.mkdir(parents=True, exist_ok=True)
        for ym in (["-"] if kind == "oro" else months):
            name = pat.format(ym=ym)
            dst = out_dir / name
            if dst.exists() and not a.overwrite:
                print(f"[{kind} {ym}] 있음 — 건너뜀", flush=True)
                continue
            config.require_nas()
            free = shutil.disk_usage(config.DATA_DIR).free / 2**30
            if free < a.min_free_gib:
                print(f"[{kind} {ym}] 중단: 로컬 여유 {free:.1f} GiB < {a.min_free_gib} GiB", flush=True)
                return
            t0 = time.time()
            for k in range(4):  # NAS(SMB over Tailscale) 일시 끊김 대비 — 30·60·90 s 대기 후 재시도
                try:
                    res = cut(src_dir / name, dst)
                    break
                except (OSError, KeyError) as e:  # KeyError: 열기 실패 시 xarray 파일 캐시가 내는 오류
                    config.require_nas()  # 마운트가 없으면 기다리지 않고 중단
                    if k == 3:
                        raise
                    print(f"  재시도 {k + 1}/3 ({30 * (k + 1)} s 후): {name} — {e}", flush=True)
                    time.sleep(30 * (k + 1))
            rec = {"kind": kind, "month": ym, "src": str(src_dir / name), **res}
            rec["elapsed_s"] = round(time.time() - t0, 1)
            with open(log, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[{kind} {ym}] {rec['dims']} · {rec['bytes'] / 2**20:.0f} MiB · 대조 {rec['center_point_equal']} · "
                  f"{rec['elapsed_s']} s", flush=True)


if __name__ == "__main__":
    main()
