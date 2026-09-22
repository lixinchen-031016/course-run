from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from course_run.config import Config, paths
from course_run.expression import AUTOPLAY_EXPRESSION, NEXT_VIDEO_EXPRESSION, PLAYBACK_TOGGLE_EXPRESSION, PREVIOUS_VIDEO_EXPRESSION, render_expression, render_resume_expression
from course_run.platform_adapter import system_name
from course_run.controller import CourseController
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
        self.assertIn("currentResources[targetIndex]?.click()", NEXT_VIDEO_EXPRESSION)
        self.assertIn("已学完", NEXT_VIDEO_EXPRESSION)

    def test_previous_video_expression_exists(self):
        self.assertIn("previousIndex", PREVIOUS_VIDEO_EXPRESSION)
        self.assertIn("currentResources[index - 1]?.click()", PREVIOUS_VIDEO_EXPRESSION)

    def test_autoplay_expression_skips_completed_items(self):
        self.assertIn("skip-completed", AUTOPLAY_EXPRESSION)
        self.assertIn("已学完", AUTOPLAY_EXPRESSION)
        self.assertIn("findNextIncomplete", AUTOPLAY_EXPRESSION)
        self.assertIn("duration - 0.35", AUTOPLAY_EXPRESSION)
        self.assertIn("action: 'next-resource'", AUTOPLAY_EXPRESSION)

    def test_resume_expression_replaces_index_and_time(self):
        expression = render_resume_expression(7, 123.5)
        self.assertIn("Number('7')", expression)
        self.assertIn("Number('123.5')", expression)
        self.assertNotIn("__RESUME_INDEX__", expression)
        self.assertNotIn("__RESUME_TIME__", expression)

    def test_playback_toggle_expression_exists(self):
        self.assertIn("video.pause()", PLAYBACK_TOGGLE_EXPRESSION)
        self.assertIn("await video.play()", PLAYBACK_TOGGLE_EXPRESSION)

    def test_expression_playback_rate_replacement(self):
        expression = render_expression(1.5)
        self.assertIn("Number('1.5')", expression)
        self.assertNotIn("__COURSE_PLAYBACK_RATE__", expression)


class PlatformTests(unittest.TestCase):
    def test_system_name_is_supported(self):
        self.assertIn(system_name(), {"windows", "macos", "linux"})


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self._old_data_dir = os.environ.get("COURSE_RUN_DATA_DIR")
        self._temp_data_dir = tempfile.TemporaryDirectory()
        os.environ["COURSE_RUN_DATA_DIR"] = self._temp_data_dir.name

    def tearDown(self):
        self._temp_data_dir.cleanup()
        if self._old_data_dir is None:
            os.environ.pop("COURSE_RUN_DATA_DIR", None)
        else:
            os.environ["COURSE_RUN_DATA_DIR"] = self._old_data_dir

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

    def test_controller_switch_commands_use_correct_expression(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"

        with patch.object(controller, "_evaluate", return_value={"value": {"ok": True, "from": "A", "to": "B"}}) as evaluate_mock, \
             patch.object(controller, "_wait_and_poll"), \
             patch.object(controller, "_recover_once"):
            controller._command_switch("next")
            self.assertEqual(evaluate_mock.call_args.args[0], NEXT_VIDEO_EXPRESSION)
            self.assertEqual(controller.snapshot()["action"], "switching-next")

        with patch.object(controller, "_evaluate", return_value={"value": {"ok": True, "from": "B", "to": "A"}}) as evaluate_mock, \
             patch.object(controller, "_wait_and_poll"), \
             patch.object(controller, "_recover_once"):
            controller._command_switch("previous")
            self.assertEqual(evaluate_mock.call_args.args[0], PREVIOUS_VIDEO_EXPRESSION)
            self.assertEqual(controller.snapshot()["action"], "switching-previous")

    def test_controller_resume_uses_saved_position(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        with patch.object(controller, "_evaluate", return_value={"value": {"ok": True}}) as evaluate_mock, \
             patch.object(controller, "_wait_and_poll"), \
             patch.object(controller, "_recover_once"):
            controller._resume_saved_position({"resourceIndex": 7, "currentTime": 123.5, "lesson": "Lesson 7"})
            expression = evaluate_mock.call_args.args[0]
            self.assertIn("Number('7')", expression)
            self.assertIn("Number('123.5')", expression)
            self.assertEqual(controller.snapshot()["lesson"], "Lesson 7")


if __name__ == "__main__":
    unittest.main()
