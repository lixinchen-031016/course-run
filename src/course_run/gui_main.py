from __future__ import annotations

import sys


def self_test() -> int:
    from course_run import __version__
    from course_run.config import Config
    from course_run.expression import AUTOPLAY_EXPRESSION

    config = Config.from_dict({"course_url": "https://example.com/course"})
    assert config.course_url == "https://example.com/course"
    assert "next-resource" in AUTOPLAY_EXPRESSION
    print(f"CourseRun {__version__} self-test passed")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    from course_run.gui import launch_gui

    launch_gui()
