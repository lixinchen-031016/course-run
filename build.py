from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
GUI_ENTRY = ROOT / "src" / "course_run" / "gui_main.py"
CLI_ENTRY = ROOT / "src" / "course_run" / "__main__.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def run_pyinstaller(name: str, windowed: bool, entry: Path, extra: list[str] | None = None) -> None:
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
    args.append(str(entry))
    print(">", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the CourseRun GUI with PyInstaller")
    parser.add_argument("--with-cli", action="store_true", help="Also build the developer CLI")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt", file=sys.stderr)
        return 1

    run_pyinstaller("CourseRun", windowed=True, entry=GUI_ENTRY)
    if args.with_cli:
        run_pyinstaller("course-run-cli", windowed=False, entry=CLI_ENTRY)
    else:
        stale = DIST / "course-run-cli"
        if stale.exists():
            stale.unlink()
    print(f"Build complete: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
