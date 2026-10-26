# CLAUDE.md — Capstone 프로젝트

> ⚡ 간결하게 유지. 상세 내용은 각 하위 문서 참고.

---

## 프로젝트 개요

| 항목 | 내용 |
|---|---|
| **주제** | 미정 (TODO) |
| **소속/과목** | 미정 (TODO) |
| **팀원** | 미정 (TODO) |
| **지도교수** | 미정 (TODO) |
| **기간** | 미정 (TODO) |
| **저장소** | https://github.com/NinjaTurtle-max/Capstone (공개 — 자료·인증키 커밋 금지) |
| **최종 산출물** | 미정 (TODO) — 예: 보고서, 발표자료, 코드 |

---

## 디렉토리 구조

```
Capstone/
├── CLAUDE.md             ← 이 파일 (프로젝트 메모리)
├── config.py             ← 경로(NAS·산출)·연구 박스·기간 상수 (환경 변수로 덮어쓰기)
├── .gitignore            ← data/·dist/·「기상, 지점 관측/」(원본 2.9GB·인증키) 제외
├── scripts/
│   ├── slice_tropomi.py  ← TROPOMI NO₂ 화소 → 한반도 박스 월별 parquet (2020–23: NAS parquet, 2024: 원본 L2 .nc)
│   ├── slice_era5.py     ← ERA5 sl·pbl·pl·지형 → 한반도 박스 월별 netCDF
│   ├── fetch_era5_sfc.py ← CDS ERA5 u10·v10·u100·v100·d2m → 박스 월별 netCDF (NAS 에 없는 변수)
│   ├── download_kma.py   ← 기상청 ASOS 단일 시각 다운로드 → data/kma (인증키 config.KMA_KEY_FILE)
│   ├── prep_airkorea.py  ← 에어코리아 월별 xlsx → parquet (원본 값 보존 + time_kst·utc·no2_ppb·no2_flag·dual_network, 기초분석 대조)
│   ├── selftest.py       ← 실행 환경 자체 시험 (같은 granule 두 원천 비교, 기대 667/808행)
│   └── inventory.py      ← 산출 현황표 data/_manifest/INVENTORY.md (+ --ref 로 파일럿 대조)
├── nas_pc/               ← NAS PC(Windows) 실행 패키지 원본: bat 4개·requirements·PC 지시서·build_zip.py
├── dist/                 ← capstone_nas_pc.zip (build_zip.py 산출, git 제외)
├── docs/                 ← preprocessing_steps.md (자료별 전처리 단계표·역할 분담)
└── data/                 ← 슬라이스 산출 (git 제외)
    ├── airkorea/         ← airkorea_YYYYMM.parquet (중복 제거·시간 구간 해석·망 선별 미적용)
    ├── tropomi/          ← tropomi_kr_YYYYMM.parquet
    ├── era5/{sl,pbl,pl}/ ← 원천 파일명 그대로, era5/oro/era5_orography.nc
    ├── era5/sfc/         ← era5_sfc_YYYYMM.nc (CDS 직접 다운로드, 값 변환 없음)
    ├── kma/              ← kma_sfctm2_<tm>_stn-<지점>.txt (download_kma.py)
    └── _manifest/        ← 월별 점검값 JSON·실행 로그
```

- 박스: 31–45.5°N, 122–134°E (한반도 + 완충 2°), 기간 2020-01 ~ 2024-12 (2026-09-30 확정).
- 실행 환경: conda env `NO2_Proxy_XCO2` (pyarrow·netCDF4·xarray). NAS 는 읽기 전용.
- TROPOMI 2020–23 은 대체로 qa ≥ 0.66 화소만(2020-04~07 일부 궤도에 qa 0.61–0.62 1,193행, 0.0094%)·픽셀 경계 없음, 2024 는 qa 전 범위·경계 포함 (`source` 열로 구분).

> 하위 폴더는 자료가 생기는 대로 추가하고 위 트리를 갱신한다.

---

## 파일 읽기 방법

| 형식 | 방법 |
|---|---|
| `.docx` / `.pptx` | Bash + python-docx / python-pptx (Read 불가) |
| `.pdf` | Read 도구 직접 사용 |
| `.html` / `.md` | Read 도구 직접 사용 |

---

## 규칙

1. **주석·대화**: 한국어
2. **코드 스타일**: PEP8 (루트 `CLAUDE.md` 코딩 규칙 준수)
3. **경로**: 하드코딩 금지 — `config.py` 또는 환경 변수 사용
4. **대용량 파일**: `.gitignore`에 추가, 100MB 초과 CSV 커밋 금지
5. **근거 없는 수치 금지**: 확인되지 않은 값은 "미정"으로 남기고 출처가 정해지면 기입
6. **파일명이 언급되면 먼저 읽고 답한다.** 추측 답변 금지
