"""에어코리아 시간별 원본 xlsx → 월별 parquet (원본 값 보존, 파생·표시 열만 추가).

원본: config.AIRKOREA_RAW_DIR/YYYY/YYYY/YYYY년 M월.xlsx (Data 시트, 12개 칼럼)
산출: data/airkorea/airkorea_YYYYMM.parquet · 점검값 data/_manifest/airkorea.jsonl

추가 열
  time_kst     : time_raw(YYYYMMDDHH, HH 01–24)의 표기 시각. 24시는 다음 날 00시
  time_utc     : time_kst − 9 h
  no2_ppb      : 1000 × NO2(ppm), no2_flag == "valid" 인 행만
  no2_flag     : valid(숫자·유한·비음수) · blank · m999(−999) · negative · nonnum
  dual_network : 같은 측정소×시각이 여러 망으로 기재된 행 (2023–24 국가배경·교외대기 이중 기재)
  source_file · source_row : 원본 파일명·엑셀 행 번호
적용하지 않음 (사용자 결정 대기): 중복 제거, 1시간 평균 구간의 시작/끝 해석, 측정망 선별, 결측 보간.
xlsx 는 표준 라이브러리(zipfile·ElementTree)로 읽는다 — openpyxl 미설치.
점검: 기초분석(별도 도구 산출)의 월별 행 수·측정소 수·물질별 유효/빈칸/합계와 대조하고,
      파일마다 무작위 3행을 다른 읽기 경로(문자열 검색·정규식)로 다시 읽어 비교한다.

사용:
  python scripts/prep_airkorea.py --months 202001-202412 --workers 3
"""
import argparse
import csv
import html
import io
import json
import os
import random
import re
import resource
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SHEET = "xl/worksheets/sheet1.xml"
HEADER = ["지역", "망", "측정소코드", "측정소명", "측정일시", "SO2", "CO", "O3", "NO2", "PM10", "PM25", "주소"]
COLS = ["region_raw", "network", "station_id", "station_name_raw", "time_raw",
        "so2_ppm", "co_ppm", "o3_ppm", "no2_ppm", "pm10_ugm3", "pm25_ugm3", "address_raw"]
NUM = COLS[5:11]
POLL = dict(zip(NUM, HEADER[5:11]))  # 열 이름 → 기초분석 물질명
CELL_RE = re.compile(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', re.DOTALL)


def col_idx(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isdigit():
            break
        n = n * 26 + ord(ch) - 64
    return n - 1


def si_text(si) -> str:
    """공유 문자열 하나. 윗주(rPh)는 빼고 본문(t 또는 r/t)만 잇는다."""
    t = si.find(NS + "t")
    if t is not None:
        return t.text or ""
    return "".join(r.findtext(NS + "t") or "" for r in si.findall(NS + "r"))


def convert(t, v, ss):
    """셀 형식 t 와 문자열 값 v → 파이썬 값 (두 읽기 경로가 같이 쓴다)."""
    if v is None:
        return None
    if t == "s":
        return ss[int(v)]
    if t in ("str", "inlineStr", "e", "b"):  # 오류·논리값은 문자열로 남겨 nonnum 으로 표시된다
        return v
    return float(v)


def read_xlsx(path: Path):
    """Data 시트 전체 행을 읽는다. (행 값 목록, 엑셀 행 번호, 공유 문자열)"""
    with zipfile.ZipFile(path) as z:
        sheets = [s.get("name") for s in ET.parse(z.open("xl/workbook.xml")).getroot().iter(NS + "sheet")]
        if sheets != ["Data"]:
            raise ValueError(f"시트 {sheets} (기대 ['Data'])")
        ss = []
        if "xl/sharedStrings.xml" in z.namelist():
            for _, el in ET.iterparse(z.open("xl/sharedStrings.xml")):
                if el.tag == NS + "si":
                    ss.append(si_text(el))
                    el.clear()
        header, rows, rnums, sheet_data = None, [], [], None
        for ev, el in ET.iterparse(z.open(SHEET), events=("start", "end")):
            if ev == "start":
                if el.tag == NS + "sheetData":
                    sheet_data = el
                continue
            if el.tag != NS + "row":
                continue
            vals = [None] * 12
            for c in el.iter(NS + "c"):
                i = col_idx(c.get("r"))
                if i < 12:
                    t = c.get("t")
                    v = "".join(x.text or "" for x in c.iter(NS + "t")) if t == "inlineStr" else c.findtext(NS + "v")
                    vals[i] = convert(t, v, ss)
            r = int(el.get("r"))
            sheet_data.clear()  # 처리한 행을 버려 메모리를 일정하게 유지
            if header is None:
                header = vals
                continue
            rows.append(vals)
            rnums.append(r)
    if header != HEADER:
        raise ValueError(f"머리행 불일치: {header}")
    return rows, rnums, ss


def reread_rows(path: Path, targets: list, ss: list) -> dict:
    """ElementTree 와 다른 경로(문자열 검색·정규식)로 지정한 엑셀 행만 다시 읽는다 — 행 단위 대조용."""
    found, buf = {}, ""
    tags = {r: f'<row r="{r}"' for r in targets}
    with zipfile.ZipFile(path) as z, io.TextIOWrapper(z.open(SHEET), encoding="utf-8") as f:
        while len(found) < len(targets):
            chunk = f.read(1 << 22)
            if not chunk:
                break
            buf += chunk
            for r, tag in tags.items():
                i = buf.find(tag) if r not in found else -1
                j = buf.find("</row>", i) if i >= 0 else -1
                if j >= 0:
                    found[r] = buf[i:j]
            buf = buf[-(1 << 16):]  # 행 하나는 수 KB 이하 — 경계에 걸친 행을 위해 끝부분만 남긴다
    out = {}
    for r, xml in found.items():
        vals = [None] * 12
        for m in CELL_RE.finditer(xml):
            ref, attrs, inner = m.groups()
            t = (re.search(r'\bt="(\w+)"', attrs) or [None, None])[1]
            if inner is None:
                v = None
            elif t == "inlineStr":
                v = html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", inner, re.DOTALL)))
            else:
                mv = re.search(r"<v>(.*?)</v>", inner, re.DOTALL)
                v = html.unescape(mv.group(1)) if mv else None
            if col_idx(ref) < 12:
                vals[col_idx(ref)] = convert(t, v, ss)
        out[r] = vals
    return out


def norm_id(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def build(rows: list, rnums: list, fname: str) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLS)
    df["station_id"] = df["station_id"].map(norm_id)
    df["time_raw"] = df["time_raw"].map(lambda v: int(norm_id(v))).astype("int64")
    raw_no2 = df["no2_ppm"]
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    no2 = df["no2_ppm"]
    df["no2_flag"] = pd.Categorical(
        np.select([raw_no2.isna(), no2.isna(), no2 == -999, no2 < 0], ["blank", "nonnum", "m999", "negative"], "valid"),
        categories=["valid", "blank", "m999", "negative", "nonnum"])
    tr = df["time_raw"]
    day = pd.to_datetime(tr // 100, format="%Y%m%d", errors="coerce")
    hh = tr % 100
    df["time_kst"] = day + pd.to_timedelta(hh.where((hh >= 1) & (hh <= 24)), unit="h")
    df["time_utc"] = df["time_kst"] - pd.Timedelta(hours=9)
    df["no2_ppb"] = (no2 * 1000).where(df["no2_flag"] == "valid")
    df["dual_network"] = df.duplicated(["station_id", "time_raw"], keep=False)
    df["source_file"] = fname
    df["source_row"] = np.asarray(rnums, dtype="int32")
    return df


def load_refs():
    ref = config.AIRKOREA_REF_DIR
    with open(ref / "01_파일별_메타데이터.csv", encoding="utf-8-sig") as f:
        r01 = {r["period"].replace("-", ""): r for r in csv.DictReader(f)}
    with open(ref / "02_월별_물질별_품질통계.csv", encoding="utf-8-sig") as f:
        r02 = {(f"{int(r['year'])}{int(r['month']):02d}", r["pollutant"]): r for r in csv.DictReader(f)}
    return r01, r02


def checks(df: pd.DataFrame, ym: str, r01: dict, r02: dict) -> tuple:
    errors, stats = [], {}
    ref = r01[ym]
    tr = df["time_raw"]
    obs = {"rows": len(df), "station_count": int(df["station_id"].nunique()),
           "hour24_rows": int((tr % 100 == 24).sum()),
           "duplicate_extra_rows": int(df.duplicated(["station_id", "time_raw"]).sum()),
           "wrong_month_rows": int((tr // 10000 != int(ym)).sum()),
           "bad_timestamps": int(df["time_kst"].isna().sum())}
    for k, v in obs.items():
        want = len(json.loads(ref[k])) if k == "bad_timestamps" else int(ref[k])
        if v != want:
            errors.append(f"{k} {v} (기초분석 {want})")
    # 24시 → 다음 날 00시, 표기 시각이 그 달 01시 ~ 다음 달 1일 00시 안
    t0 = pd.Timestamp(f"{ym[:4]}-{ym[4:]}-01 01:00")
    t1 = (t0 - pd.Timedelta(hours=1)) + pd.offsets.MonthBegin(1)
    h24 = df.loc[tr % 100 == 24, "time_kst"]
    if not ((h24.dt.hour == 0).all() and df["time_kst"].between(t0, t1).all()):
        errors.append("time_kst 범위·24시 변환 이상")
    dup = df[df["dual_network"]]
    other = NUM + ["region_raw", "station_name_raw", "address_raw"]
    obs["dual_network_rows"] = len(dup)
    obs["dual_conflicts"] = int((dup.groupby(["station_id", "time_raw"])[other].nunique(dropna=False) > 1)
                                .any(axis=1).sum()) if len(dup) else 0
    if obs["dual_conflicts"]:
        errors.append(f"이중 기재 값 충돌 {obs['dual_conflicts']}건")
    for c, p in POLL.items():
        v = df[c]
        s = {"blank": int(v.isna().sum()), "sentinel_minus999": int((v == -999).sum()),
             "other_negative": int(((v < 0) & (v != -999)).sum()), "valid": int((v >= 0).sum()),
             "sum": float(v[v >= 0].sum())}
        r = r02[(ym, p)]
        for k in ("blank", "sentinel_minus999", "other_negative", "valid"):
            if s[k] != int(r[k]):
                errors.append(f"{p} {k} {s[k]} (기초분석 {r[k]})")
        if abs(s["sum"] - float(r["sum"])) > 1e-9 * max(1.0, abs(float(r["sum"]))):
            errors.append(f"{p} 합계 {s['sum']} (기초분석 {r['sum']})")
        stats[p] = s
    flags = df["no2_flag"].value_counts().to_dict()
    obs["no2_flag"] = {k: int(v) for k, v in flags.items() if v}
    return obs, stats, errors


def process(ym: str) -> dict:
    t0 = time.time()
    y, m = ym[:4], int(ym[4:])
    ydir = config.nas_child(config.nas_child(config.AIRKOREA_RAW_DIR, y), y)
    src = config.nas_child(ydir, f"{y}년 {m}월.xlsx")
    dst = config.AIRKOREA_OUT / f"airkorea_{ym}.parquet"
    rows, rnums, ss = read_xlsx(src)
    df = build(rows, rnums, src.name)
    r01, r02 = load_refs()
    obs, stats, errors = checks(df, ym, r01, r02)
    # 행 단위 대조: 무작위 3행을 다른 읽기 경로로 다시 읽어 원본 값 목록이 같은지
    rng = random.Random(int(ym))
    picks = rng.sample(range(len(rows)), 3)
    again = reread_rows(src, [rnums[k] for k in picks], ss)
    spot = [rnums[k] for k in picks if again.get(rnums[k]) != rows[k]]
    if spot:
        errors.append(f"행 대조 불일치 엑셀 행 {spot}")
    del rows
    tmp = dst.with_name(dst.name + ".tmp")
    df.to_parquet(tmp, index=False, compression="zstd")
    back = pd.read_parquet(tmp, columns=["station_id", "time_raw", "no2_ppm", "source_row"])
    if len(back) != len(df) or not back["source_row"].equals(df["source_row"]) \
            or not np.allclose(back["no2_ppm"], df["no2_ppm"], equal_nan=True):
        errors.append("parquet 재읽기 불일치")
    rec = {"month": ym, "src": src.name, **obs, "pollutants": stats, "spot_rows": [rnums[k] for k in picks],
           "bytes": tmp.stat().st_size, "errors": errors, "elapsed_s": round(time.time() - t0, 1),
           "max_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)}
    os.replace(tmp, dst.with_name(dst.name + ".failed") if errors else dst)
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", default="-".join(config.PERIOD), help="YYYYMM-YYYYMM")
    ap.add_argument("--workers", type=int, default=3, help="Mac 메모리 8 GiB — 월 1개당 최대 RSS 를 보고 정한다")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    a0, a1 = a.months.split("-")
    months = [p.strftime("%Y%m") for p in pd.period_range(pd.Period(a0, "M"), pd.Period(a1, "M"), freq="M")]
    config.AIRKOREA_OUT.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_OUT.mkdir(parents=True, exist_ok=True)
    todo = [ym for ym in months if a.overwrite or not (config.AIRKOREA_OUT / f"airkorea_{ym}.parquet").exists()]
    print(f"대상 {len(months)}개월 · 건너뜀 {len(months) - len(todo)} · 처리 {len(todo)} · workers {a.workers}", flush=True)
    failed = []
    with Pool(a.workers, maxtasksperchild=1) as pool:  # 달마다 새 프로세스 — 메모리 누적 방지
        for rec in pool.imap_unordered(process, todo):
            with open(config.MANIFEST_OUT / "airkorea.jsonl", "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            state = f"점검 실패 {rec['errors']}" if rec["errors"] else "점검 통과"
            print(f"[{rec['month']}] {rec['rows']:,}행 · 측정소 {rec['station_count']} · {rec['bytes'] / 2**20:.1f} MiB · "
                  f"{rec['elapsed_s']} s · RSS {rec['max_rss_mib']} MiB · {state}", flush=True)
            if rec["errors"]:
                failed.append(rec["month"])
    print(f"완료 {len(todo) - len(failed)}/{len(todo)} · 실패 {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
