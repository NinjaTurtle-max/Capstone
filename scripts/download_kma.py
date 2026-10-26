"""기상청 ASOS 단일 시각 자료 다운로드. Python 표준 라이브러리만 사용.

인증키: config.KMA_KEY_FILE (환경 변수 CAP_KMA_KEY 로 덮어쓰기) · 산출: config.KMA_OUT (data/kma)
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

API_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"

# Spyder에서 실행할 때 아래 기본값을 변경할 수 있습니다.
DEFAULT_TM = "202211300900"  # YYYYMMDDHHMM, 한국표준시(KST)
DEFAULT_STN = "0"  # 0: 전체 ASOS 지점. 여러 지점: "108:104"
DEFAULT_HELP = 1


def decode_response(raw):
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("응답 문자 인코딩을 해석하지 못했습니다.")


def validate_response(text, tm, stn):
    """인증 오류/HTML/빈 응답/다른 시각 자료를 정상 데이터로 저장하지 않음."""
    rows = []
    requested = None if stn == "0" else set(stn.split(":"))
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4 or not re.fullmatch(r"\d{12}", fields[0]):
            raise ValueError("정상 관측자료가 아닙니다. API 활용신청, 키 및 조회 조건을 확인하세요.")
        if fields[0] != tm or not fields[1].isdigit():
            raise ValueError("응답의 관측시각 또는 지점 형식이 요청과 일치하지 않습니다.")
        if requested is not None and str(int(fields[1])) not in requested:
            raise ValueError("요청하지 않은 지점이 응답에 포함되어 있습니다.")
        rows.append(fields)
    if not rows:
        raise ValueError("관측 행이 없습니다. 인증/권한/자료 보유 여부를 확인하세요.")
    return rows


def download(tm=DEFAULT_TM, stn=DEFAULT_STN, help_value=DEFAULT_HELP,
             key_file=None, out_dir=None, timeout=60):
    # 브라우저 URL에 포함된 후행 공백은 키 파일의 strip()으로 제거됩니다.
    if not re.fullmatch(r"\d{12}", tm):
        raise ValueError("tm은 YYYYMMDDHHMM 형식이어야 합니다.")
    datetime.strptime(tm + "+0900", "%Y%m%d%H%M%z")  # 실재하는 KST 시각인지 검사
    if not re.fullmatch(r"\d+(?::\d+)*", stn):
        raise ValueError("stn은 0 또는 지점번호(:로 구분)로 입력하세요.")
    stn = ":".join(str(int(item)) for item in stn.split(":"))
    if "0" in stn.split(":") and stn != "0":
        raise ValueError("전체 지점인 0은 다른 지점번호와 함께 사용하지 마세요.")
    if help_value not in (0, 1) or timeout <= 0:
        raise ValueError("help는 0/1, timeout은 양수로 입력하세요.")
    key_path = Path(key_file) if key_file is not None else config.KMA_KEY_FILE
    key = key_path.read_text(encoding="utf-8-sig").strip()
    if not key or any(ch.isspace() for ch in key):
        raise ValueError("api_key.txt에 인증키 한 줄만 입력하세요.")
    params = {"tm": tm, "stn": stn, "help": help_value, "authKey": key}
    request = Request(API_URL + "?" + urlencode(params),
                      headers={"User-Agent": "KMA-research-downloader/1.0"})
    # 키가 포함된 요청 URL이나 서버 오류 본문을 출력하지 않습니다.
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        raise RuntimeError("기상청 API HTTP 오류: " + str(exc.code)) from None
    except (URLError, TimeoutError):  # socket.timeout 은 3.10 부터 TimeoutError 별칭
        raise RuntimeError("기상청 연결 실패 또는 시간초과. 네트워크를 확인하세요.") from None
    text, source_encoding = decode_response(raw)
    rows = validate_response(text, tm, stn)
    if key in text:
        raise ValueError("응답에 인증키가 포함되어 있어 저장을 중단했습니다.")
    destination = Path(out_dir) if out_dir is not None else config.KMA_OUT
    destination.mkdir(parents=True, exist_ok=True)
    station_label = "all" if stn == "0" else stn.replace(":", "-")
    path = destination / ("kma_sfctm2_" + tm + "_stn-" + station_label + ".txt")
    # 필드 설명과 결측 표식을 보존하며 UTF-8로 저장합니다.
    path.write_text(text, encoding="utf-8")
    print("저장 완료:", path)
    print("관측시각(KST):", tm, "| 관측 행:", len(rows),
          "| 원본 인코딩:", source_encoding)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tm", default=DEFAULT_TM, help="YYYYMMDDHHMM (KST)")
    parser.add_argument("--stn", default=DEFAULT_STN, help="0 또는 108:104 등")
    parser.add_argument("--help-fields", type=int, choices=(0, 1), default=DEFAULT_HELP)
    parser.add_argument("--key-file", type=Path, default=config.KMA_KEY_FILE)
    parser.add_argument("--out-dir", type=Path, default=config.KMA_OUT)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    try:
        download(args.tm, args.stn, args.help_fields, args.key_file,
                 args.out_dir, args.timeout)
    except (OSError, ValueError, RuntimeError) as exc:
        print("다운로드 실패:", str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
