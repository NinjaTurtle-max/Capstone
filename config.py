"""Capstone 경로·상수 설정. 경로는 환경 변수로 덮어쓸 수 있다.

CAP_NAS_MOUNT : NAS 공유 루트 (dataset·S5P_L2… 가 있는 곳) — 읽기 전용으로만 쓴다
                기본: Mac 은 /Volumes/100.118.65.89, Windows(NAS PC)는 C–H 드라이브 중 dataset\\NO2-Proxy-XCO2 가 있는 곳
CAP_DATA_DIR  : 슬라이스 산출 루트 (기본 <이 파일이 있는 폴더>/data)
"""
import os
import unicodedata
from pathlib import Path


def _default_mount() -> str:
    if os.name != "nt":
        return "/Volumes/100.118.65.89"
    for d in "CDEFGH":
        if (Path(f"{d}:\\") / "dataset" / "NO2-Proxy-XCO2").is_dir():
            return f"{d}:\\"
    return "E:\\"


def _norm_mount(p: str) -> Path:
    """'E:' 처럼 드라이브 문자만 주면 드라이브 현재 폴더 기준이 되므로 루트('E:\\')로 바꾼다."""
    if os.name == "nt" and len(p) == 2 and p.endswith(":"):
        p += "\\"
    return Path(p)


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CAP_DATA_DIR", ROOT / "data"))
NAS_MOUNT = _norm_mount(os.environ.get("CAP_NAS_MOUNT", _default_mount()))


def require_nas() -> None:
    """NAS 마운트가 없으면 명확한 메시지로 즉시 중단한다 (재마운트는 사용자가 한다)."""
    if not os.path.ismount(NAS_MOUNT):
        raise SystemExit(f"NAS 마운트 없음: {NAS_MOUNT} — Mac 은 재마운트, PC 는 _env.bat 의 CAP_NAS_MOUNT 를 "
                         "dataset 이 있는 드라이브 루트(예: E:\\)로 지정")


def nas_child(parent: Path, name: str) -> Path:
    """SMB 가 한글 이름을 NFD 로 돌려주므로 NFC 정규화 비교로 하위 경로를 찾는다."""
    for e in os.scandir(parent):
        if unicodedata.normalize("NFC", e.name) == name:
            return Path(e.path)
    raise FileNotFoundError(f"'{name}' 없음: {parent}")


# 원천 (NAS, 읽기 전용)
def tropomi_v2_dir() -> Path:
    """2020–2024 granule parquet 8,011개 (대체로 qa 정수값 ≥ 66 — 일부 궤도 61–62, 20–50°N·100–150°E, 픽셀 경계 없음)."""
    return nas_child(NAS_MOUNT / "dataset", "XCO2연구 데이터") / "_tropomi_ea_v2"


TROPOMI_L2_2024_DIR = NAS_MOUNT / "S5P_L2__NO2____HiR_2-20260227_051530"  # 2024 원본 L2 .nc 1,596개
ERA5_PL_DIR = NAS_MOUNT / "dataset" / "NO2-Proxy-XCO2" / "era5_pl_raw"      # era5_pl_*·era5_sl_*·orography
ERA5_PBL_DIR = NAS_MOUNT / "dataset" / "NO2-Proxy-XCO2" / "era5_wind_z100"  # 파생 PBL풍 (z_min=100 m)

# 에어코리아 원본 (로컬, 읽기 전용) — 월별 xlsx 60개 YYYY/YYYY/YYYY년 M월.xlsx
AIRKOREA_RAW_DIR = Path(os.environ.get("CAP_AIRKOREA_RAW", ROOT / "기상, 지점 관측" / "새 폴더"))
# 다른 도구로 만든 원본 기초분석 — 전처리 결과의 독립 대조 기준
AIRKOREA_REF_DIR = Path(os.environ.get("CAP_AIRKOREA_REF", ROOT / "기상, 지점 관측" / "NO2_2020_2024_기초분석"))
# 기상청 API허브 인증키 한 줄 (로컬 전용 — .gitignore 로 커밋 제외)
KMA_KEY_FILE = Path(os.environ.get("CAP_KMA_KEY", ROOT / "기상, 지점 관측" / "api_key.txt"))

# 산출
TROPOMI_OUT = DATA_DIR / "tropomi"
ERA5_OUT = DATA_DIR / "era5"
AIRKOREA_OUT = DATA_DIR / "airkorea"
KMA_OUT = DATA_DIR / "kma"
MANIFEST_OUT = DATA_DIR / "_manifest"

# 연구 범위 (2026-09-30 사용자 확정)
PERIOD = ("202001", "202412")
# 한반도(33–43.5°N, 124–132°E) + 상풍향 완충 2° — 6 h 시차 × 약 10 m/s ≈ 2°
BOX = {"lat_min": 31.0, "lat_max": 45.5, "lon_min": 122.0, "lon_max": 134.0}
