# NAS PC(Windows) — 캡스톤 한반도 슬라이스 실행 지시 (Claude Code에 붙여 넣기)

## 배경

캡스톤 연구(TROPOMI–에어코리아 시간별 지상 NO₂ 재구성)에 쓸 위성·기상 자료를 **한반도 + 완충 2° 박스(31–45.5°N, 122–134°E), 2020-01 ~ 2024-12**로 잘라 둔다. 맥에서 SMB(Tailscale)로 읽다가 2026-09-30 16:36에 마운트가 끊겨 중단됐으므로(패킷 손실 33 %), **이 PC의 로컬 디스크에서 직접 실행**한다. 원천은 읽기만 한다.

맥 파일럿(2020-01 ~ 07)에서 측정한 값: TROPOMI 월 205–230 MiB, ERA5 단일층 월 10 MiB · PBL풍 23 MiB · 기압면 120 MiB, 점검값(박스 밖 화소·다른 달 시각·중복) 모두 0. **전체 예상 용량 약 23 GiB**(2024 TROPOMI는 원본 .nc에서 경계 열까지 뽑으므로 추정). PC 소요 시간은 미측정.

| 원천 (읽기 전용) | 내용 |
|---|---|
| `<드라이브>:\dataset\XCO2연구 데이터\_tropomi_ea_v2\` | TROPOMI granule parquet 8,011개 (2020–2023 슬라이스 원천) |
| `<드라이브>:\S5P_L2__NO2____HiR_2-20260227_051530\` | 2024 원본 L2 .nc 1,596개 (2024 슬라이스 원천, 픽셀 경계 포함) |
| `<드라이브>:\dataset\NO2-Proxy-XCO2\era5_pl_raw\` | `era5_sl_*`·`era5_pl_*` 각 60개 + `era5_orography.nc` |
| `<드라이브>:\dataset\NO2-Proxy-XCO2\era5_wind_z100\` | `era5_wind_*_z100.nc` 60개 |

## 파일 (zip 을 풀어 `<드라이브>:\dataset\Capstone\` 에 둔다 — `config.py` 가 이 폴더 바로 아래 있어야 한다)

zip 안 최상위 폴더가 `Capstone\` 이므로 `<드라이브>:\dataset\` 를 대상으로 푼다. Windows "모두 추출"은 zip 이름 폴더(`capstone_nas_pc\`)를 한 단계 더 만들 수 있으니, 그 경우 안쪽 `Capstone\` 폴더를 `dataset\` 바로 아래로 옮긴다.

| 파일 | 역할 |
|---|---|
| `config.py` | 경로·박스·기간. NAS 루트는 C–H 중 `dataset\NO2-Proxy-XCO2` 가 있는 드라이브를 자동 탐지 (`CAP_NAS_MOUNT` 로 덮어쓰기) |
| `scripts\slice_tropomi.py` | TROPOMI → `data\tropomi\tropomi_kr_YYYYMM.parquet`. 2020–23 은 parquet 원천, 2024 는 원본 .nc(qa 전 범위 + 픽셀 경계). 재개형 |
| `scripts\slice_era5.py` | ERA5 sl·pbl·pl·oro → `data\era5\<종류>\` (원천 파일명 그대로). 재개형 |
| `scripts\selftest.py` | 자체 시험. 같은 granule 을 두 원천으로 뽑아 비교 (기대: 667행 · 808행 · 열 전부 일치) + ERA5 한 달 자르기 |
| `scripts\inventory.py` | 현황표 `data\_manifest\INVENTORY.md` + 맥 파일럿과 행 수 대조 |
| `_env.bat` · `setup.bat` · `run_selftest.bat` · `run_all.bat` | 환경 · 패키지 설치 · 자체 시험 · 전체 순차 실행 (로그 `logs\`) |
| `pilot_mac_manifest\` | 맥 파일럿 2020-01 ~ 07 점검값 (대조 기준) |

## 지시

1. `<드라이브>:\dataset\Capstone\config.py` 가 있는지, NAS 드라이브 문자와 여유 공간을 표로 알려줘. 여유가 **33 GiB 미만**(산출 23 + 유지 기준 10)이면 멈추고 보고해라.
2. `setup.bat` 실행 → 마지막 줄 `OK …` 와 버전을 보고. 실패하면 `where python` 으로 numpy·pandas·pyarrow·netCDF4·xarray 가 되는 python 을 찾아 `_env.bat` 의 `PY` 줄만 고쳐라.
3. `run_selftest.bat` 실행 → `SELFTEST OK` 와 종료 코드 0 확인. 아니면 **멈추고** `logs\selftest.log` 전체를 보고해라 (스크립트를 고치지 말 것).
4. `run_all.bat` 를 **별도 창에서** 실행. 15분 뒤 `logs\run_all.log` 마지막 10줄을 보여주고, 월당 소요 시간으로 전체 예상 완료 시각을 계산해 알려줘.
5. 멈추면 같은 `run_all.bat` 를 다시 실행해라 (끝난 달은 건너뜀). **같은 오류로 3번 실패하면 중단**하고 로그 마지막 30줄을 보고해라. 메모리 오류면 bat 의 `--workers 4` 를 2 로 낮추는 것만 허용한다.
6. 끝나면 `data\_manifest\INVENTORY.md` 전체를 보여주고 아래 표를 채워 보고해라.

| 항목 | 값 |
|---|---|
| NAS 드라이브 · 여유 공간 (시작 / 끝) | |
| Python 경로 · 패키지 버전 5종 | |
| SELFTEST 결과 | |
| 월당 소요 (TROPOMI 2020–23 / 2024 / ERA5 pl) · 총 소요 | |
| INVENTORY 요약 (완료/전체 · 이상) | |
| 맥 파일럿 대조 (2020-01 ~ 07) | |

## 수용 기준

- INVENTORY: TROPOMI 60/60, ERA5 sl·pbl·pl 각 60/60, oro 1/1, 이상 0
- 맥 파일럿 대조 7개월 모두 "일치"
- 월별 매니페스트(`data\_manifest\tropomi_YYYYMM.json`)의 `outside_box`·`obs_time_outside_month`·`duplicates` 모두 0

## 하지 말 것

- 원천 폴더(`_tropomi_ea_v2`, `S5P_L2__NO2____HiR_2-…`, `era5_pl_raw`, `era5_wind_z100`)를 삭제·이동·이름 변경·수정하지 말 것. 스크립트는 `dataset\Capstone\` 아래에만 쓴다.
- 박스·열 정의·qa 처리·검사 로직을 고치지 말 것. 경로 문제는 `CAP_NAS_MOUNT`·`CAP_DATA_DIR` 환경 변수나 `_env.bat` 로만 해결.
- 이 PC를 절전·재부팅하지 말 것. Tailscale·공유 설정을 바꾸지 말 것.
