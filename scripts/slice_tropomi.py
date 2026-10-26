"""TROPOMI NO₂ 화소 → 한반도 박스 월별 parquet.

원천
  2020–2023 : NAS `_tropomi_ea_v2` granule parquet — 대체로 qa 정수값 ≥ 66 (2020-04~07 일부 궤도에 61–62 존재), 픽셀 경계 없음
  2024      : NAS 원본 L2 .nc — qa 전 범위 + 픽셀 경계(lat_b0–3·lon_b0–3) + scanline·ground_pixel
두 원천의 열 이름·자료형·정의를 통일한다. .nc → 열 대응은 2024-01-04 궤도 32259 에서
parquet 와 35개 값 열·행 순서가 비트 단위로 일치함을 확인했다 (qa 정수 ≥ 66 조건).
obs_time 은 원천 parquet 와 같게 스캔라인 time_utc 를 초 단위로 절삭한 UTC 시각이다.
qa 임계값은 적용하지 않는다 — 분석 단계에서 정한다.

사용:
  python scripts/slice_tropomi.py --months 202001-202012
  python scripts/slice_tropomi.py --months 202401 --source nc
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

FNAME = re.compile(r"S5P_(OFFL|RPRO)_L2__NO2____(\d{8})T\d{6}_\d{8}T\d{6}_(\d{5})_\d{2}_(\d{6})_")
DROP = {"date", "no2_tvcd_umol"}  # obs_time·no2_tvcd 와 중복

G, I, D = "SUPPORT_DATA/GEOLOCATIONS/", "SUPPORT_DATA/INPUT_DATA/", "SUPPORT_DATA/DETAILED_RESULTS/"
# 출력 열 이름 → L2 .nc 변수 경로 (PRODUCT 그룹 기준)
NC_VARS = {
    "lat": "latitude", "lon": "longitude", "qa": "qa_value",
    "no2_tvcd": "nitrogendioxide_tropospheric_column",
    "no2_tvcd_precision": "nitrogendioxide_tropospheric_column_precision",
    "amf_trop": "air_mass_factor_troposphere", "amf_total": "air_mass_factor_total",
    "tm5_tropopause_idx": "tm5_tropopause_layer_index",
    "surface_pressure": I + "surface_pressure", "surface_altitude": I + "surface_altitude",
    "surface_classification": I + "surface_classification",
    "surface_albedo_no2win": I + "surface_albedo_nitrogendioxide_window",
    "cloud_pressure_crb": I + "cloud_pressure_crb", "cloud_fraction_crb": I + "cloud_fraction_crb",
    "cloud_albedo_crb": I + "cloud_albedo_crb", "scene_albedo": I + "scene_albedo",
    "apparent_scene_pressure": I + "apparent_scene_pressure", "snow_ice_flag": I + "snow_ice_flag",
    "aerosol_index_354_388": I + "aerosol_index_354_388",
    "eastward_wind": I + "eastward_wind", "northward_wind": I + "northward_wind",
    "no2_strat_column": D + "nitrogendioxide_stratospheric_column",
    "no2_total_column": D + "nitrogendioxide_total_column",
    "no2_scd": D + "nitrogendioxide_slant_column_density",
    "cloud_radiance_fraction": D + "cloud_radiance_fraction_nitrogendioxide_window",
    "cloud_fraction_no2win": D + "cloud_fraction_crb_nitrogendioxide_window",
    "amf_strat": D + "air_mass_factor_stratosphere", "amf_cloudy": D + "air_mass_factor_cloudy",
    "amf_clear": D + "air_mass_factor_clear", "no2_ghost_column": D + "nitrogendioxide_ghost_column",
    "no2_geometric_column": D + "nitrogendioxide_geometric_column",  # 일부 처리 버전에만 존재
    "sza": G + "solar_zenith_angle", "saa": G + "solar_azimuth_angle",
    "vza": G + "viewing_zenith_angle", "vaa": G + "viewing_azimuth_angle",
}
BOUND_COLS = [f"lat_b{k}" for k in range(4)] + [f"lon_b{k}" for k in range(4)]
SCHEMA = pa.schema(
    [("source", pa.string()), ("orbit", pa.int32()), ("proc_type", pa.string()),
     ("proc_ver", pa.string()), ("obs_time", pa.timestamp("ms"))]
    + [(c, pa.float32()) for c in NC_VARS]
    + [("scanline", pa.int16()), ("ground_pixel", pa.int16())]
    + [(c, pa.float32()) for c in BOUND_COLS]
)


def box_mask(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """화소 중심이 박스 안(경계 포함)이면 True. NaN 은 False."""
    b = config.BOX
    return (lat >= b["lat_min"]) & (lat <= b["lat_max"]) & (lon >= b["lon_min"]) & (lon <= b["lon_max"])


def _to_schema(cols: dict, n: int) -> pa.Table:
    """열 dict → 통일 스키마 테이블. 없는 열은 null 로 채운다."""
    arrays = []
    for f in SCHEMA:
        v = cols.get(f.name)
        if v is None:
            arrays.append(pa.nulls(n, f.type))
        elif isinstance(v, (pa.Array, pa.ChunkedArray)):
            arrays.append(v.cast(f.type))
        else:
            arrays.append(pa.array(v, type=f.type))
    return pa.Table.from_arrays(arrays, schema=SCHEMA)


def from_v2(path: str):
    """granule parquet → (박스 화소 테이블 | None, 상태, 없는 원천 열)."""
    pf = pq.ParquetFile(path)
    names = pf.schema_arrow.names
    if pf.metadata.num_rows == 0 or "lat" not in names:
        return None, "empty", []
    ll = pf.read(columns=["lat", "lon"])
    m = box_mask(np.asarray(ll["lat"]), np.asarray(ll["lon"]))
    if not m.any():
        return None, "nobox", []
    t = pf.read(columns=[c for c in names if c not in DROP]).filter(pa.array(m))
    n = t.num_rows
    cols = {c: t[c] for c in t.column_names}
    cols["source"] = pa.array(["v2"] * n, pa.string())
    missing = [c for c in NC_VARS if c not in names]
    return _to_schema(cols, n), "ok", missing


def from_nc(path: str):
    """원본 L2 .nc → (박스 화소 테이블 | None, 상태, 없는 변수). qa 조건 없이 박스 안 전 화소."""
    import netCDF4 as nc

    proc_type, _, orbit, proc_ver = FNAME.search(os.path.basename(path)).groups()
    with nc.Dataset(path) as ds:
        p = ds["PRODUCT"]
        lat = np.ma.filled(p["latitude"][0], np.nan)
        lon = np.ma.filled(p["longitude"][0], np.nan)
        m = box_mask(lat, lon)
        if not m.any():
            return None, "nobox", []
        rows = np.flatnonzero(m.any(axis=1))
        s0, s1 = int(rows[0]), int(rows[-1]) + 1
        sub = m[s0:s1]
        r, c = np.nonzero(sub)  # 행 우선 순서 = 불리언 색인 순서
        n = len(r)
        cols, missing = {"lat": lat[s0:s1][sub], "lon": lon[s0:s1][sub]}, []
        for col, vpath in NC_VARS.items():
            if col in cols:
                continue
            try:
                v = p[vpath]
            except (IndexError, KeyError):
                missing.append(col)
                continue
            cols[col] = np.ma.filled(v[0, s0:s1, :].astype(np.float32), np.nan)[sub]
        tu = pd.Series(np.asarray(p["time_utc"][0, s0:s1], dtype=str)).str.slice(0, 19)
        t_sl = pd.to_datetime(tu, format="%Y-%m-%dT%H:%M:%S", errors="coerce").to_numpy()
        cols["obs_time"] = t_sl[r].astype("datetime64[ms]")
        cols["scanline"] = (r + s0).astype(np.int16)
        cols["ground_pixel"] = c.astype(np.int16)
        for name, key in (("lat", "latitude_bounds"), ("lon", "longitude_bounds")):
            bnd = np.ma.filled(p[G + key][0, s0:s1, :, :], np.nan)[sub]
            for k in range(4):
                cols[f"{name}_b{k}"] = bnd[:, k].astype(np.float32)
    cols.update(source=np.full(n, "l2nc", dtype=object), orbit=np.full(n, int(orbit), np.int32),
                proc_type=np.full(n, proc_type, dtype=object), proc_ver=np.full(n, proc_ver, dtype=object))
    return _to_schema(cols, n), "ok", missing


def list_by_month(src_dir: Path, ext: str) -> dict:
    """원천 디렉토리 → {YYYYMM: [파일 경로, …]} (파일명 궤도 시작일 기준, 시간순)."""
    out = {}
    for e in os.scandir(src_dir):
        mo = FNAME.search(e.name)
        if mo and e.name.endswith(ext):
            out.setdefault(mo.group(2)[:6], []).append(e.path)
    return {k: sorted(v) for k, v in out.items()}


def check(tbl: pa.Table, ym: str) -> dict:
    """수용 기준 점검값: 박스 이탈·월 이탈·중복 화소 수 등."""
    lat, lon = tbl["lat"].to_numpy(), tbl["lon"].to_numpy()
    ot = pd.DatetimeIndex(tbl["obs_time"].to_numpy())
    df = tbl.select(["orbit", "obs_time", "lat", "lon"]).to_pandas()
    return {
        "rows": tbl.num_rows,
        "outside_box": int((~box_mask(lat, lon)).sum()),
        "obs_time_outside_month": int((ot.strftime("%Y%m") != ym).sum()),
        "obs_time_nat": int(ot.isna().sum()),
        "duplicates": int(df.duplicated().sum()),
        "orbits": int(pd.unique(df["orbit"]).size),
        "qa_min": float(np.nanmin(tbl["qa"].to_numpy())),
        "lat_range": [float(np.nanmin(lat)), float(np.nanmax(lat))],
        "lon_range": [float(np.nanmin(lon)), float(np.nanmax(lon))],
        "obs_time_range": [str(ot.min()), str(ot.max())],
        "proc": dict(Counter(f"{a} {b}" for a, b in zip(tbl["proc_type"].to_pylist(), tbl["proc_ver"].to_pylist()))),
    }


def with_retry(fn, path: str, tries: int = 4, wait: float = 30.0):
    """NAS(SMB over Tailscale) 일시 끊김 대비 — 입출력 오류는 30·60·90 s 대기 후 재시도, 그래도 실패하면 예외."""
    for k in range(tries):
        try:
            return fn(path)
        except OSError as e:
            if k == tries - 1 or not os.path.ismount(config.NAS_MOUNT):  # 마운트가 없으면 기다려도 소용없음
                raise
            print(f"  재시도 {k + 1}/{tries - 1} ({wait * (k + 1):.0f} s 후): {os.path.basename(path)} — {e}", flush=True)
            time.sleep(wait * (k + 1))


def run_month(ym: str, files: list, source: str, workers: int, overwrite: bool) -> dict:
    out = config.TROPOMI_OUT / f"tropomi_kr_{ym}.parquet"
    if out.exists() and not overwrite:
        print(f"[{ym}] 있음 — 건너뜀", flush=True)
        return {}
    t0 = time.time()
    fn, pool = (from_v2, ThreadPoolExecutor) if source == "v2" else (from_nc, ProcessPoolExecutor)
    with pool(max_workers=workers) as ex:
        res = list(ex.map(partial(with_retry, fn), files))
    parts = [t for t, _, _ in res if t is not None]
    status = Counter(s for _, s, _ in res)
    missing = Counter(c for _, _, ms in res for c in ms)
    rec = {"month": ym, "source": source, "granules": len(files), "status": dict(status),
           "missing_source_cols": dict(missing), "box": config.BOX}
    if parts:
        tbl = pa.concat_tables(parts)
        rec.update(check(tbl, ym))
        tmp = out.with_name(out.name + ".tmp")
        pq.write_table(tbl, tmp, compression="zstd", row_group_size=500_000)
        os.replace(tmp, out)
        rec["bytes"] = out.stat().st_size
    rec["elapsed_s"] = round(time.time() - t0, 1)
    (config.MANIFEST_OUT / f"tropomi_{ym}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    print(f"[{ym}] {source} granule {len(files)} {dict(status)} → 행 {rec.get('rows', 0):,} · "
          f"{rec.get('bytes', 0) / 2**20:.0f} MiB · {rec['elapsed_s']} s · 박스이탈 {rec.get('outside_box')} · "
          f"월이탈 {rec.get('obs_time_outside_month')} · 중복 {rec.get('duplicates')}", flush=True)
    return rec


def parse_months(s: str) -> list:
    if "-" in s:
        a, b = s.split("-")
        return [p.strftime("%Y%m") for p in pd.period_range(pd.Period(a, "M"), pd.Period(b, "M"), freq="M")]
    return s.split(",")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", required=True, help="YYYYMM-YYYYMM 또는 YYYYMM,YYYYMM")
    ap.add_argument("--source", choices=["auto", "v2", "nc"], default="auto", help="auto: 2024 는 nc, 나머지는 v2")
    ap.add_argument("--workers", type=int, default=3, help="NAS 동시 읽기 수 (원격 연결이 불안정하면 낮춘다)")
    ap.add_argument("--min-free-gib", type=float, default=10.0, help="로컬 여유가 이 값 아래로 내려가면 중단")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    config.require_nas()
    for d in (config.TROPOMI_OUT, config.MANIFEST_OUT):
        d.mkdir(parents=True, exist_ok=True)
    months = parse_months(a.months)
    need = {("nc" if a.source == "nc" or (a.source == "auto" and m.startswith("2024")) else "v2") for m in months}
    listing = {}
    if "v2" in need:
        listing["v2"] = list_by_month(config.tropomi_v2_dir(), ".parquet")
    if "nc" in need:
        listing["nc"] = list_by_month(config.TROPOMI_L2_2024_DIR, ".nc")
    for ym in months:
        config.require_nas()
        src = "nc" if a.source == "nc" or (a.source == "auto" and ym.startswith("2024")) else "v2"
        free = shutil.disk_usage(config.DATA_DIR).free / 2**30
        if free < a.min_free_gib:
            print(f"[{ym}] 중단: 로컬 여유 {free:.1f} GiB < {a.min_free_gib} GiB", flush=True)
            break
        run_month(ym, listing[src].get(ym, []), src, a.workers, a.overwrite)


if __name__ == "__main__":
    main()
