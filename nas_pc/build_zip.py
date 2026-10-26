"""NAS PC 실행 패키지 → dist/capstone_nas_pc.zip (Mac 에서 실행).

zip 안 최상위 폴더는 Capstone/ — <드라이브>:\\dataset\\ 에 풀면 <드라이브>:\\dataset\\Capstone\\config.py 가 된다.
.bat 은 cmd 가 안정적으로 읽도록 CRLF 로 바꿔 넣는다. 맥 파일럿 매니페스트를 대조 기준으로 동봉한다.
"""
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import config

FILES = {
    "config.py": ROOT / "config.py",
    **{f"scripts/{n}": ROOT / "scripts" / n for n in ("slice_tropomi.py", "slice_era5.py", "selftest.py", "inventory.py")},
    **{n: HERE / n for n in ("_env.bat", "setup.bat", "run_selftest.bat", "run_all.bat", "requirements.txt",
                              "pc_capstone_prompt.md")},
    **{f"pilot_mac_manifest/{p.name}": p for p in sorted(config.MANIFEST_OUT.glob("tropomi_2*.json"))},
}


def main():
    out = ROOT / "dist" / "capstone_nas_pc.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in FILES.items():
            data = src.read_bytes()
            if src.suffix == ".bat":
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            z.writestr(f"Capstone/{arc}", data)
    print(out, f"{out.stat().st_size / 1024:.0f} KiB", len(FILES), "파일")


if __name__ == "__main__":
    main()
