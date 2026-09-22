from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "src" / "course_run" / "__main__.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def run_pyinstaller(name: str, windowed: bool, extra: list[str] | None = None) -> None:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--paths",
        str(ROOT / "src"),
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / name),
        "--specpath",
        str(BUILD / "spec"),
    ]
    args.append("--windowed" if windowed else "--console")
    if platform.system() == "Darwin":
        args.extend(["--osx-bundle-identifier", "com.lixinchen.courserun"])
    args.extend(extra or [])
    args.append(str(ENTRY))
    print(">", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CourseRun executables with PyInstaller")
    parser.add_argument("--gui-only", action="store_true")
    parser.add_argument("--cli-only", action="store_true")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt", file=sys.stderr)
        return 1

    if not args.cli_only:
        run_pyinstaller("CourseRun", windowed=True)
    if not args.gui_only:
        run_pyinstaller("course-run-cli", windowed=False)
    print(f"构建完成: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
