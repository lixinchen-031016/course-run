from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from course_run.config import Config, paths
from course_run.expression import AUTOPLAY_EXPRESSION, NEXT_VIDEO_EXPRESSION, render_expression
from course_run.platform_adapter import system_name
from course_run.manager import next_video
from course_run.worker import recover_playback, run_worker


class ConfigTests(unittest.TestCase):
    def test_config_normalization(self):
        config = Config.from_dict({
            "course_url": "  https://example.com/course  ",
            "poll_seconds": 0,
            "playback_rate": 9,
        })
        self.assertEqual(config.course_url, "https://example.com/course")
        self.assertEqual(config.poll_seconds, 10)
        self.assertEqual(config.playback_rate, 4.0)


class ExpressionTests(unittest.TestCase):
    def test_expression_has_control_actions(self):
        for action in ["next-resource", "complete", "resume", "dismissed-modal", "wait-video"]:
            self.assertIn(action, AUTOPLAY_EXPRESSION)

    def test_next_video_expression_exists(self):
        self.assertIn("nextIndex", NEXT_VIDEO_EXPRESSION)
        self.assertIn("currentResources[index + 1]?.click()", NEXT_VIDEO_EXPRESSION)

    def test_expression_playback_rate_replacement(self):
        expression = render_expression(1.5)
        self.assertIn("Number('1.5')", expression)
        self.assertNotIn("__COURSE_PLAYBACK_RATE__", expression)


class PlatformTests(unittest.TestCase):
    def test_system_name_is_supported(self):
        self.assertIn(system_name(), {"windows", "macos", "linux"})


class WorkerTests(unittest.TestCase):
    def test_worker_once_writes_status(self):
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.get("COURSE_RUN_DATA_DIR")
            os.environ["COURSE_RUN_DATA_DIR"] = directory
            try:
                state = Path(directory) / "state.json"
                state.write_text(json.dumps({
                    "session_id": "test-session",
                    "tab_id": "test-tab",
                    "owns_session": False,
                    "poll_seconds": 2,
                    "switch_delay_seconds": 1,
                    "retry_limit": 2,
                    "playback_rate": 1,
                }), encoding="utf-8")
                from unittest.mock import patch
                with patch("course_run.worker.bsk.run_json", return_value={
                    "value": {
                        "action": "playing",
                        "lesson": "Lesson 1",
                        "resourceIndex": 1,
                        "resourceCount": 3,
                        "currentTime": 5,
                        "duration": 100,
                        "paused": False,
                        "ended": False,
                    }
                }):
                    run_worker(state, once=True)
                status = json.loads(paths().status.read_text(encoding="utf-8"))
                self.assertEqual(status["state"], "running")
                self.assertEqual(status["lesson"], "Lesson 1")
                self.assertEqual(status["resourceCount"], 3)
            finally:
                if old is None:
                    os.environ.pop("COURSE_RUN_DATA_DIR", None)
                else:
                    os.environ["COURSE_RUN_DATA_DIR"] = old

    def test_recovery_escalates_to_reload(self):
        from unittest.mock import patch
        with patch("course_run.worker.activate_browser"), \
             patch("course_run.worker.bsk.run") as run_mock, \
             patch("course_run.worker.bsk.reload") as reload_mock:
            recover_playback("session", "tab", 1)
            self.assertTrue(any("click" in call.args[0] for call in run_mock.call_args_list))
            self.assertFalse(reload_mock.called)

            run_mock.reset_mock()
            recover_playback("session", "tab", 3)
            reload_mock.assert_called_once_with("session", "tab")

    def test_next_video_returns_switched_item(self):
        from unittest.mock import patch
        responses = [
            {"value": {"ok": True, "from": "Lesson 1", "to": "Lesson 2", "nextIndex": 2, "count": 3}},
            {"value": {"action": "playing"}},
        ]
        with patch("course_run.manager._evaluate_with_retry", side_effect=responses), \
             patch("course_run.manager.time.sleep"):
            result = next_video(session_id="session", tab_id="tab")
        self.assertTrue(result["ok"])
        self.assertEqual(result["to"], "Lesson 2")
        self.assertEqual(result["session_id"], "session")


if __name__ == "__main__":
    unittest.main()
