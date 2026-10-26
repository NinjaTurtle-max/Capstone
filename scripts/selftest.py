"""실행 환경 자체 시험 — 본 실행 전에 돌린다. 실패하면 종료 코드 1.

1. 같은 granule(2024-01-04 궤도 32259)을 두 원천 경로(NAS parquet·원본 L2 .nc)로 추출해
   행 수가 기대값과 같고, 겹치는 화소(qa 정수 ≥ 66)의 모든 열이 같은지 확인한다.
   기대값 (Mac, 2026-09-30): parquet 경로 667행 · .nc 경로 808행 · .nc 중 qa ≥ 0.66 667행 · 불일치 열 없음.
2. ERA5 단일층 2020-01 을 임시 폴더로 잘라 격자가 59×49 이고 중앙 격자점 값이 원천과 같은지 확인한다.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import slice_era5
import slice_tropomi as st

import config

GRANULE = "20240104T032459"
EXPECT = {"v2": 667, "nc": 808}


def main():
    import netCDF4
    import pandas
    import xarray

    print("python", sys.version.split()[0], "| numpy", np.__version__, "| pandas", pandas.__version__,
          "| pyarrow", pa.__version__, "| netCDF4", netCDF4.__version__, "| xarray", xarray.__version__)
    print("NAS 루트:", config.NAS_MOUNT, "| 산출 루트:", config.DATA_DIR)
    config.require_nas()

    v2 = next(p for p in st.list_by_month(config.tropomi_v2_dir(), ".parquet")["202401"] if GRANULE in p)
    l2 = next(p for p in st.list_by_month(config.TROPOMI_L2_2024_DIR, ".nc")["202401"] if GRANULE in p)
    a, _, _ = st.from_v2(v2)
    b, _, _ = st.from_nc(l2)
    assert a.schema == b.schema == st.SCHEMA, "스키마 불일치"
    assert (a.num_rows, b.num_rows) == (EXPECT["v2"], EXPECT["nc"]), f"행 수 {a.num_rows}/{b.num_rows} ≠ 기대 {EXPECT}"
    bb = b.filter(pa.array(np.rint(np.asarray(b["qa"]) * 100) >= 66))
    skip = {"source", "scanline", "ground_pixel", *st.BOUND_COLS}
    diff = [c for c in st.SCHEMA.names if c not in skip and not a[c].equals(bb[c])]
    assert bb.num_rows == a.num_rows and not diff, f"겹치는 화소 불일치: 행 {bb.num_rows}/{a.num_rows}, 열 {diff}"
    print(f"[1] TROPOMI 두 경로 일치: parquet {a.num_rows}행 · nc {b.num_rows}행 · 겹침 {bb.num_rows}행 전 열 동일")

    with tempfile.TemporaryDirectory() as tmp:
        rec = slice_era5.cut(config.ERA5_PL_DIR / "era5_sl_202001.nc", Path(tmp) / "era5_sl_202001.nc")
    dims = (rec["dims"].get("latitude"), rec["dims"].get("longitude"))
    assert dims == (59, 49) and rec["center_point_equal"], f"ERA5 자르기 이상: {rec}"
    print(f"[2] ERA5 단일층 2020-01: 격자 {dims} · 중앙 격자점 원천과 같음")
    print("SELFTEST OK")


if __name__ == "__main__":
    main()
