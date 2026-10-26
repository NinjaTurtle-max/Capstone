"""슬라이스 산출 현황 점검 → data/_manifest/INVENTORY.md.

파일마다 매니페스트 기록(행 수·크기·격자·원천 대조)과 실제 파일을 대조해 완료·미완료·이상을 센다.
--ref <폴더> 를 주면 그 폴더의 tropomi_YYYYMM.json(예: Mac 파일럿)과 같은 달의 점검값을 비교한다.

사용:
  python scripts/inventory.py
  python scripts/inventory.py --ref pilot_mac_manifest
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

ERA5_NAME = {"sl": "era5_sl_{ym}.nc", "pbl": "era5_wind_{ym}_z100.nc", "pl": "era5_pl_{ym}.nc"}
CMP_KEYS = ("rows", "outside_box", "obs_time_outside_month", "duplicates", "orbits", "qa_min")


def months() -> list:
    a, b = config.PERIOD
    return [p.strftime("%Y%m") for p in pd.period_range(pd.Period(a, "M"), pd.Period(b, "M"), freq="M")]


def ranges(yms: list) -> str:
    """['202008', '202009', '202011'] → '202008–202009, 202011'."""
    if not yms:
        return "—"
    ps = sorted(pd.Period(y, "M") for y in yms)
    out, s, e = [], ps[0], ps[0]
    for p in ps[1:]:
        if p == e + 1:
            e = p
        else:
            out.append(s.strftime("%Y%m") + ("" if s == e else "–" + e.strftime("%Y%m")))
            s = e = p
    out.append(s.strftime("%Y%m") + ("" if s == e else "–" + e.strftime("%Y%m")))
    return ", ".join(out)


def check_tropomi() -> tuple:
    rows, bad = [], []
    for ym in months():
        f = config.TROPOMI_OUT / f"tropomi_kr_{ym}.parquet"
        m = config.MANIFEST_OUT / f"tropomi_{ym}.json"
        if not f.exists():
            continue
        rec = json.loads(m.read_text()) if m.exists() else {}
        n = pq.ParquetFile(f).metadata.num_rows
        ok = (rec.get("rows") == n and rec.get("bytes") == f.stat().st_size and rec.get("outside_box") == 0
              and rec.get("obs_time_outside_month") == 0 and rec.get("duplicates") == 0)
        rows.append({"month": ym, "rows": n, "bytes": f.stat().st_size, "ok": ok, "rec": rec})
        if not ok:
            bad.append(ym)
    return rows, bad


def check_era5() -> dict:
    log = config.MANIFEST_OUT / "era5.jsonl"
    recs = {}
    if log.exists():
        for line in log.read_text().splitlines():
            r = json.loads(line)
            recs[(r["kind"], r["month"])] = r  # 같은 파일을 다시 자른 경우 마지막 기록
    out = {}
    for kind, pat in {**ERA5_NAME, "oro": "era5_orography.nc"}.items():
        done, bad, size = [], [], 0
        for ym in (["-"] if kind == "oro" else months()):
            f = config.ERA5_OUT / kind / pat.format(ym=ym)
            if not f.exists():
                continue
            r = recs.get((kind, ym), {})
            with xr.open_dataset(f) as ds:
                ok = (dict(ds.sizes) == r.get("dims") and f.stat().st_size == r.get("bytes")
                      and r.get("center_point_equal") is True)
            (done if ok else bad).append(ym)
            size += f.stat().st_size
        out[kind] = {"done": done, "bad": bad, "bytes": size}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", help="비교할 tropomi_YYYYMM.json 폴더 (예: Mac 파일럿 매니페스트)")
    a = ap.parse_args()

    allm = months()
    trop, trop_bad = check_tropomi()
    era = check_era5()
    tdone = [r["month"] for r in trop if r["ok"]]
    lines = [f"# 슬라이스 현황 ({datetime.now().astimezone():%Y-%m-%d %H:%M %Z})", "",
             f"- 산출 루트: `{config.DATA_DIR}` · 박스 {config.BOX} · 기간 {config.PERIOD[0]}–{config.PERIOD[1]}", "",
             "| 자료 | 완료/전체 | 크기 (GiB) | 이상 | 미완료 월 |", "|---|---|---|---|---|",
             (f"| TROPOMI | {len(tdone)}/{len(allm)} | {sum(r['bytes'] for r in trop) / 2**30:.2f} | "
              f"{ranges(trop_bad) if trop_bad else 0} | {ranges([m for m in allm if m not in tdone])} |")]
    for kind, v in era.items():
        total = 1 if kind == "oro" else len(allm)
        todo = [] if kind == "oro" else [m for m in allm if m not in v["done"]]
        miss = ("—" if v["done"] else "미실행") if kind == "oro" else ranges(todo)
        lines.append(f"| ERA5 {kind} | {len(v['done'])}/{total} | {v['bytes'] / 2**30:.2f} | "
                     f"{', '.join(v['bad']) if v['bad'] else 0} | {miss} |")
    lines += ["", "## TROPOMI 월별", "", "| 월 | 행 | MiB | 매니페스트 일치 | 처리 버전 |", "|---|---|---|---|---|"]
    for r in trop:
        lines.append(f"| {r['month']} | {r['rows']:,} | {r['bytes'] / 2**20:.0f} | {'예' if r['ok'] else '아니오'} | "
                     f"{', '.join(r['rec'].get('proc', {}))} |")
    if a.ref:
        lines += ["", f"## 참조 비교 (`{a.ref}`)", "", "| 월 | 결과 | 다른 항목 |", "|---|---|---|"]
        for r in trop:
            rf = Path(a.ref) / f"tropomi_{r['month']}.json"
            if rf.exists():
                ref = json.loads(rf.read_text())
                diff = [k for k in CMP_KEYS if ref.get(k) != r["rec"].get(k)]
                lines.append(f"| {r['month']} | {'일치' if not diff else '불일치'} | {', '.join(diff) or '—'} |")
    text = "\n".join(lines) + "\n"
    config.MANIFEST_OUT.mkdir(parents=True, exist_ok=True)
    (config.MANIFEST_OUT / "INVENTORY.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
