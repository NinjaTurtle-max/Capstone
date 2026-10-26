"""ERA5 단일층 지표 바람·이슬점 (CDS) → 한반도 박스 월별 netCDF.

NAS era5_sl 에는 blh·sp·z·t2m 만 있어 연구계획서 §4.4 의 10 m·100 m 바람과 2 m 이슬점을 CDS 에서 새로 받는다.
  변수 : u10·v10 (10 m 바람), u100·v100 (100 m 바람), d2m (2 m 이슬점) — 시간별, UTC
  영역 : config.BOX (0.25° 격자, NAS 슬라이스와 같은 격자점)
  산출 : data/era5/sfc/era5_sfc_YYYYMM.nc (CDS 파일 그대로, 값 변환 없음) · 점검값 data/_manifest/era5_sfc.jsonl
인증은 ~/.cdsapirc 를 cdsapi 가 직접 읽는다. 끝난 달은 건너뛰므로 같은 명령을 다시 돌리면 이어서 받는다.

사용:
  python scripts/fetch_era5_sfc.py --months 202001-202412
"""
import argparse
import calendar
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import cdsapi
import numpy as np
import pandas as pd
import requests
import xarray as xr
from ecmwf.datastores.processing import DownloadError, LinkError, ProcessingFailedError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

DATASET = "reanalysis-era5-single-levels"
VARS = {  # CDS 요청 이름 → 파일 변수명
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
    "100m_u_component_of_wind": "u100",
    "100m_v_component_of_wind": "v100",
    "2m_dewpoint_temperature": "d2m",
}
OUT_DIR = config.ERA5_OUT / "sfc"
# cdsapi 0.7(새 CDS)는 ecmwf.datastores 클라이언트로 요청하며 HTTP 오류·작업 실패를 아래 예외로 낸다
CDS_ERRORS = (requests.RequestException, ProcessingFailedError, DownloadError, LinkError)
# 인증·라이선스 오류는 재시도해도 같으므로 바로 중단한다
FATAL = ("401", "403", "licence", "license", "authenticat", "unauthorized", "forbidden")


def request(ym: str) -> dict:
    b = config.BOX
    y, m = int(ym[:4]), int(ym[4:])
    return {
        "product_type": ["reanalysis"],
        "variable": list(VARS),
        "year": [f"{y}"],
        "month": [f"{m:02d}"],
        "day": [f"{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [b["lat_max"], b["lon_min"], b["lat_min"], b["lon_max"]],  # N, W, S, E
    }


def check(path: Path, ym: str) -> dict:
    """수용 기준 점검. 실패 항목은 errors 에 모은다."""
    b = config.BOX
    y, m = int(ym[:4]), int(ym[4:])
    errors = []
    with xr.open_dataset(path) as ds:
        t = "valid_time" if "valid_time" in ds.coords else "time"
        times = pd.DatetimeIndex(ds[t].values)
        want = pd.date_range(f"{y}-{m:02d}-01", periods=calendar.monthrange(y, m)[1] * 24, freq="h")
        if not times.equals(want):
            errors.append(f"시각 {len(times)}개 (기대 {len(want)}개, 1시간 간격 UTC)")
        lat = np.sort(ds["latitude"].values)
        lon = np.sort(ds["longitude"].values)
        if not np.allclose(lat, np.arange(b["lat_min"], b["lat_max"] + 0.125, 0.25)):
            errors.append(f"위도 {lat.size}개 {lat.min()}–{lat.max()}")
        if not np.allclose(lon, np.arange(b["lon_min"], b["lon_max"] + 0.125, 0.25)):
            errors.append(f"경도 {lon.size}개 {lon.min()}–{lon.max()}")
        stats = {}
        for v in VARS.values():
            if v not in ds:
                errors.append(f"{v} 없음")
                continue
            a = ds[v].values
            unit = ds[v].attrs.get("units", "")
            stats[v] = {"units": unit, "nan": int(np.isnan(a).sum()),
                        "min": round(float(np.nanmin(a)), 2), "max": round(float(np.nanmax(a)), 2)}
            lo, hi, u = (190.0, 310.0, "K") if v == "d2m" else (-60.0, 60.0, "m s**-1")
            if stats[v]["nan"]:
                errors.append(f"{v} NaN {stats[v]['nan']}개")
            if unit != u:
                errors.append(f"{v} 단위 '{unit}' (기대 '{u}')")
            if not (lo <= stats[v]["min"] and stats[v]["max"] <= hi):
                errors.append(f"{v} 범위 {stats[v]['min']}–{stats[v]['max']} (허용 {lo}–{hi})")
        dims = {k: int(n) for k, n in ds.sizes.items()}
    return {"dims": dims, "stats": stats, "errors": errors}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", required=True, help="YYYYMM-YYYYMM")
    ap.add_argument("--min-free-gib", type=float, default=10.0, help="로컬 여유가 이 값 아래로 내려가면 중단")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    a0, a1 = a.months.split("-")
    months = [p.strftime("%Y%m") for p in pd.period_range(pd.Period(a0, "M"), pd.Period(a1, "M"), freq="M")]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_OUT.mkdir(parents=True, exist_ok=True)
    log = config.MANIFEST_OUT / "era5_sfc.jsonl"
    client = cdsapi.Client(progress=False, retry_max=20, sleep_max=120)
    for ym in months:
        dst = OUT_DIR / f"era5_sfc_{ym}.nc"
        if dst.exists() and not a.overwrite:
            print(f"[{ym}] 있음 — 건너뜀", flush=True)
            continue
        free = shutil.disk_usage(config.DATA_DIR).free / 2**30
        if free < a.min_free_gib:
            print(f"[{ym}] 중단: 로컬 여유 {free:.1f} GiB < {a.min_free_gib} GiB", flush=True)
            return 1
        tmp = dst.with_name(dst.name + ".tmp")
        t0 = time.time()
        for k in range(3):  # CDS 일시 오류 대비 — 작업 규칙의 재시도 상한 3회
            try:
                client.retrieve(DATASET, request(ym), str(tmp))
                break
            except CDS_ERRORS as e:
                msg = str(e)
                if any(s in msg.lower() for s in FATAL) or k == 2:
                    print(f"[{ym}] 중단 ({k + 1}회째 실패): {msg[:300]}", flush=True)
                    return 1
                print(f"  재시도 {k + 1}/2 ({60 * (k + 1)} s 후): {msg[:200]}", flush=True)
                time.sleep(60 * (k + 1))
        res = check(tmp, ym)
        rec = {"month": ym, "dataset": DATASET, "bytes": tmp.stat().st_size, "sha256": sha256(tmp), **res,
               "elapsed_s": round(time.time() - t0, 1)}
        with open(log, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if res["errors"]:
            bad = dst.with_name(dst.name + ".failed")
            os.replace(tmp, bad)
            print(f"[{ym}] 점검 실패 — {bad.name} 로 보존하고 중단: {res['errors']}", flush=True)
            return 1
        os.replace(tmp, dst)
        print(f"[{ym}] {res['dims']} · {rec['bytes'] / 2**20:.1f} MiB · 점검 통과 · {rec['elapsed_s']} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
