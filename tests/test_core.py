from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from course_run.config import Config, paths
from course_run.expression import AUTOPLAY_EXPRESSION, NEXT_VIDEO_EXPRESSION, PLAYBACK_RECOVERY_EXPRESSION, PLAYBACK_TOGGLE_EXPRESSION, PREVIOUS_VIDEO_EXPRESSION, render_expression, render_resume_expression
from course_run.platform_adapter import activate_browser, system_name
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
        for action in ["next-resource", "select-resource", "complete", "resume", "wait-video"]:
            self.assertIn(action, AUTOPLAY_EXPRESSION)
        self.assertIn("dismissedModal", AUTOPLAY_EXPRESSION)
        self.assertIn("activeIndex < 0 && firstIncomplete", AUTOPLAY_EXPRESSION)
        self.assertIn("speed-warning", AUTOPLAY_EXPRESSION)
        self.assertIn("speedWarning", AUTOPLAY_EXPRESSION)
        self.assertIn("须学习完课程的视频才可获得该课程视频的学时", AUTOPLAY_EXPRESSION)

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

    def test_playback_recovery_expression_never_clicks_video(self):
        self.assertIn("await video.play()", PLAYBACK_RECOVERY_EXPRESSION)
        self.assertNotIn("video.click()", PLAYBACK_RECOVERY_EXPRESSION)
        self.assertIn("reason", PLAYBACK_RECOVERY_EXPRESSION)


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

    def test_windows_activation_prefers_native_window_restore(self):
        from unittest.mock import patch
        with patch("course_run.platform_adapter.system_name", return_value="windows"), \
             patch("course_run.platform_adapter._restore_windows_browser", return_value=True) as restore_mock:
            self.assertTrue(activate_browser(title_hint="Course"))
            restore_mock.assert_called_once_with("Microsoft Edge", "Course")

    def test_controller_recovery_respects_cooldown(self):
        import time
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._next_recovery_at = time.time() + 10
        with patch("course_run.controller.bsk.run") as run_mock, \
             patch("course_run.controller.activate_browser") as activate_mock:
            controller._recover_once(allow_reload=False)
            self.assertEqual(controller._recovery_attempts, 0)
            run_mock.assert_not_called()
            activate_mock.assert_not_called()

    def test_controller_resets_watchdog_when_resource_changes(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._last_resource_index = 1
        controller._last_current_time = 1074.0
        controller._recovery_attempts = 2
        controller._stalled_since = 900.0
        controller._loading_until = 0.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "playing",
            "resourceIndex": 2,
            "resourceCount": 10,
            "currentTime": 3.0,
            "duration": 600,
            "paused": False,
        }}), patch.object(controller, "_recover_once") as recover_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        self.assertEqual(controller._last_resource_index, 2)
        self.assertEqual(controller._last_current_time, 3.0)
        self.assertEqual(controller._recovery_attempts, 0)
        self.assertIsNone(controller._stalled_since)
        recover_mock.assert_not_called()

    def test_controller_ignores_backwards_seek_without_recovery(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._last_resource_index = 1
        controller._last_current_time = 500.0
        controller._last_duration = 600.0
        controller._recovery_attempts = 2
        controller._stalled_since = 900.0
        controller._loading_until = 0.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "playing",
            "resourceIndex": 1,
            "resourceCount": 10,
            "currentTime": 2.0,
            "duration": 600,
            "paused": False,
        }}), patch.object(controller, "_recover_once") as recover_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        self.assertEqual(controller._last_current_time, 2.0)
        self.assertEqual(controller._recovery_attempts, 0)
        recover_mock.assert_not_called()

    def test_controller_handles_speed_warning_with_single_reload(self):
        from unittest.mock import patch
        from course_run.config import load_config, save_config
        save_config(playback_rate=2.0)
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._speed_warning_since = 995.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "speed-warning",
            "resourceIndex": 1,
            "resourceCount": 31,
            "currentTime": 50,
            "duration": 100,
            "paused": True,
            "playbackRate": 1.0,
        }}), patch("course_run.controller.bsk.reload") as reload_mock, \
             patch.object(controller, "_recover_once") as recover_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        reload_mock.assert_called_once_with("session", "tab")
        self.assertEqual(controller._pending_resource_index, 1)
        self.assertEqual(controller._speed_warning_reloads, 1)
        self.assertEqual(load_config().playback_rate, 1.0)
        recover_mock.assert_not_called()

    def test_controller_does_not_reload_speed_warning_twice(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._speed_warning_since = 990.0
        controller._speed_warning_reloads = 1
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "speed-warning",
            "resourceIndex": 1,
            "resourceCount": 31,
            "currentTime": 50,
            "duration": 100,
            "paused": True,
            "playbackRate": 1.0,
        }}), patch("course_run.controller.bsk.reload") as reload_mock, \
             patch("course_run.controller.time.time", return_value=1030.0):
            controller._poll()
        reload_mock.assert_not_called()

    def test_controller_selects_first_resource_when_active_index_is_unknown(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._complete_since = 900.0
        controller._loading_until = 2000.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "select-resource",
            "resourceIndex": 0,
            "resourceCount": 31,
            "currentTime": 0,
            "duration": 0,
            "paused": None,
            "nextResourceIndex": 1,
        }}), patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        self.assertEqual(controller._pending_resource_index, 1)
        self.assertIsNone(controller._complete_since)
        self.assertFalse(controller._complete_confirmed)

    def test_controller_ignores_transient_complete_with_empty_catalog(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._owns_session = True
        controller._loading_until = 2000.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "complete",
            "resourceIndex": 0,
            "resourceCount": 0,
            "currentTime": 0,
            "duration": 0,
            "paused": True,
        }}), patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        self.assertEqual(controller._session_id, "session")
        self.assertFalse(controller._complete_confirmed)
        self.assertIsNone(controller._complete_since)
        self.assertNotEqual(controller.snapshot()["state"], "complete")

    def test_controller_confirms_complete_without_closing_session(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._owns_session = True
        controller._last_resource_index = 3
        controller._last_current_time = 0.0
        controller._last_duration = 0.0
        controller._complete_since = 993.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "complete",
            "resourceIndex": 3,
            "resourceCount": 10,
            "currentTime": 0,
            "duration": 100,
            "paused": True,
        }}), patch("course_run.controller.bsk.run") as run_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        self.assertTrue(controller._complete_confirmed)
        self.assertEqual(controller.snapshot()["state"], "complete")
        self.assertEqual(controller._session_id, "session")
        self.assertFalse(any(call.args and call.args[0][:2] == ["session", "stop"] for call in run_mock.call_args_list))

    def test_controller_switches_when_natural_end_resets_to_zero(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._last_resource_index = 9
        controller._last_current_time = 99.5
        controller._last_duration = 100.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "playing",
            "resourceIndex": 9,
            "resourceCount": 10,
            "currentTime": 0.0,
            "duration": 100.0,
            "paused": True,
        }}), patch.object(controller, "_command_switch") as switch_mock, \
             patch.object(controller, "_recover_once") as recover_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        switch_mock.assert_called_once_with("next")
        recover_mock.assert_not_called()

    def test_controller_next_resource_resets_watchdog_immediately(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._last_resource_index = 1
        controller._last_current_time = 1074.0
        controller._recovery_attempts = 2
        controller._next_recovery_at = 0.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "next-resource",
            "resourceIndex": 1,
            "resourceCount": 10,
            "currentTime": 1074.0,
            "duration": 1074.0,
            "paused": False,
            "nextResourceIndex": 2,
        }}), patch.object(controller, "_recover_once") as recover_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        self.assertEqual(controller._last_current_time, 0.0)
        self.assertEqual(controller._recovery_attempts, 0)
        self.assertEqual(controller._pending_resource_index, 2)
        recover_mock.assert_not_called()

    def test_controller_restores_pending_resource_instead_of_reloading(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._last_resource_index = 1
        controller._last_current_time = 100.0
        controller._pending_resource_index = 3
        controller._next_recovery_at = 0.0
        controller._loading_until = 0.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "action": "playing",
            "resourceIndex": 1,
            "resourceCount": 10,
            "currentTime": 101.0,
            "duration": 600,
            "paused": False,
        }}), patch.object(controller, "_recover_pending_resource") as pending_mock, \
             patch.object(controller, "_recover_once") as recover_mock, \
             patch("course_run.controller.time.time", return_value=1000.0):
            controller._poll()
        pending_mock.assert_called_once_with()
        recover_mock.assert_not_called()

    def test_controller_pending_recovery_uses_resume_expression(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._pending_resource_index = 3
        controller._next_recovery_at = 0.0
        with patch.object(controller, "_evaluate", return_value={"value": {
            "ok": True,
            "reason": "changed",
            "targetIndex": 3,
        }}) as evaluate_mock, patch("course_run.controller.bsk.run"), \
             patch("course_run.controller.activate_browser"):
            controller._recover_pending_resource()
        expression = evaluate_mock.call_args.args[0]
        self.assertIn("Number('3')", expression)
        self.assertIn("Number('0.0')", expression)

    def test_controller_gentle_recovery_uses_play_not_click(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._next_recovery_at = 0.0
        controller._last_current_time = 10.0
        with patch.object(controller, "_evaluate", return_value={"value": {"ok": True, "reason": "playing"}}) as evaluate_mock, \
             patch("course_run.controller.bsk.run") as run_mock, \
             patch("course_run.controller.activate_browser"):
            controller._recover_once(allow_reload=False)
        evaluate_mock.assert_called_once()
        self.assertEqual(evaluate_mock.call_args.args[0], PLAYBACK_RECOVERY_EXPRESSION)
        self.assertFalse(any("click" in call.args[0] for call in run_mock.call_args_list))

    def test_controller_second_recovery_clicks_videojs_play_button(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._next_recovery_at = 0.0
        controller._recovery_attempts = 1
        controller._last_current_time = 10.0
        with patch("course_run.controller.bsk.run") as run_mock, \
             patch("course_run.controller.activate_browser"):
            controller._recover_once(allow_reload=False)
        click_calls = [call for call in run_mock.call_args_list if "click" in call.args[0]]
        self.assertTrue(click_calls)
        self.assertEqual(click_calls[0].args[0][2], "button.vjs-big-play-button")

    def test_autoplay_blocked_clicks_videojs_on_first_recovery(self):
        from unittest.mock import patch
        controller = CourseController()
        controller._session_id = "session"
        controller._tab_id = "tab"
        controller._next_recovery_at = 0.0
        controller._last_current_time = 10.0
        blocked = {
            "ok": False,
            "reason": "still-paused",
            "paused": True,
            "playError": {"name": "NotAllowedError", "message": "blocked"},
        }
        with patch.object(controller, "_evaluate", return_value={"value": blocked}), \
             patch("course_run.controller.bsk.run") as run_mock, \
             patch("course_run.controller.activate_browser"):
            controller._recover_once(allow_reload=False)
        click_calls = [call for call in run_mock.call_args_list if "click" in call.args[0]]
        self.assertTrue(click_calls)
        self.assertEqual(click_calls[0].args[0][2], "button.vjs-big-play-button")


if __name__ == "__main__":
    unittest.main()
