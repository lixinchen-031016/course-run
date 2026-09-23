from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from typing import Any

_CRASH_HANDLE: Any = None


def self_test() -> int:
    from course_run import __version__
    from course_run.config import Config
    from course_run.expression import AUTOPLAY_EXPRESSION

    config = Config.from_dict({"course_url": "https://example.com/course"})
    assert config.course_url == "https://example.com/course"
    assert "next-resource" in AUTOPLAY_EXPRESSION
    print(f"CourseRun {__version__} self-test passed")
    return 0


def _install_crash_logging() -> None:
    global _CRASH_HANDLE
    from course_run.config import paths
    from course_run.platform_adapter import ensure_dir

    path = paths().root / "crash.log"
    ensure_dir(path.parent)
    _CRASH_HANDLE = path.open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(_CRASH_HANDLE, all_threads=True)

    def exception_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        traceback.print_exception(exc_type, exc, tb, file=_CRASH_HANDLE)

    def thread_hook(args: Any) -> None:
        traceback.print_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            file=_CRASH_HANDLE,
        )

    sys.excepthook = exception_hook
    threading.excepthook = thread_hook


def main() -> int:
    from course_run.gui import launch_gui
    from course_run.single_instance import acquire_instance_lock, show_already_running

    _install_crash_logging()
    lock = acquire_instance_lock()
    if lock is None:
        show_already_running()
        return 2
    try:
        launch_gui()
    except BaseException:
        traceback.print_exc()
        raise
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
