from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import bsk
from .config import Config, load_config, paths, read_status, save_config, write_status
from .expression import (
    NEXT_VIDEO_EXPRESSION,
    PLAYBACK_RECOVERY_EXPRESSION,
    PLAYBACK_TOGGLE_EXPRESSION,
    PREVIOUS_VIDEO_EXPRESSION,
    render_expression,
    render_resume_expression,
)
from .platform_adapter import activate_browser


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _busy_error(error: Exception) -> bool:
    message = str(error).lower()
    return "session_busy" in message or "unfinished command" in message


class CourseController:
    """Single-process, serialized browser controller used directly by the GUI."""

    def __init__(self, on_update: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.on_update = on_update
        self._commands: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "state": "idle",
            "action": "idle",
            "lesson": "",
            "resourceIndex": 0,
            "resourceCount": 0,
            "currentTime": 0.0,
            "duration": 0.0,
            "progressPct": 0.0,
            "paused": None,
            "session_id": None,
            "tab_id": None,
            "browser_id": None,
            "course_url": "",
            "error": None,
            "updated_at": utc_now(),
        }
        self._session_id: str | None = None
        self._tab_id: str | None = None
        self._owns_session = False
        self._recovery_attempts = 0
        self._stalled_since: float | None = None
        self._last_progress_time = time.time()
        self._last_current_time = 0.0
        self._last_resource_index = 0
        self._recovery_anchor_current = 0.0
        self._loading_until = 0.0
        self._next_recovery_at = 0.0
        self._reload_attempts = 0
        self._pending_resource_index = 0
        self._pending_recovery_attempts = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="course-controller", daemon=True)
        self._thread.start()

    def submit(self, command: str, **payload: Any) -> None:
        self._commands.put((command, payload))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def shutdown(self, stop_session: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            self._commands.put(("shutdown", {"stop_session": stop_session}))
            self._thread.join(timeout=8)
        self._stop_event.set()

    def _update(self, **patch: Any) -> None:
        with self._lock:
            self._state.update(patch)
            self._state["updated_at"] = utc_now()
            state = dict(self._state)
        try:
            write_status(state)
        except Exception:
            pass
        if self.on_update:
            try:
                self.on_update(state)
            except Exception:
                pass

    def _log(self, message: str) -> None:
        path = paths().log
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_now()} {message}\n")

    def _reset_progress_watchdog(
        self,
        current_time: float,
        resource_index: int | None,
        now: float,
        *,
        grace: float = 8.0,
        reason: str = "",
    ) -> None:
        """Reset progress tracking after a resource change, seek, or reload."""
        self._last_current_time = max(0.0, float(current_time or 0))
        if resource_index is not None:
            self._last_resource_index = max(0, int(resource_index or 0))
        self._last_progress_time = now
        self._stalled_since = None
        self._recovery_attempts = 0
        self._recovery_anchor_current = self._last_current_time
        self._reload_attempts = 0
        self._loading_until = max(self._loading_until, now + max(0.0, grace))
        self._next_recovery_at = max(self._next_recovery_at, now + 2.0)
        if reason:
            self._log(reason)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                command, payload = self._commands.get(timeout=0.8)
            except queue.Empty:
                if self._session_id:
                    self._safe_poll()
                continue
            try:
                if command == "start":
                    self._command_start(payload)
                elif command == "stop":
                    self._command_stop()
                elif command == "toggle":
                    self._command_toggle()
                elif command == "next":
                    self._command_switch("next")
                elif command == "previous":
                    self._command_switch("previous")
                elif command == "shutdown":
                    if payload.get("stop_session", True):
                        self._command_stop()
                    break
            except Exception as exc:
                self._log(f"{command} failed: {exc}")
                self._update(state="error", action="error", error=str(exc))

    def _safe_poll(self) -> None:
        try:
            self._poll()
        except Exception as exc:
            self._log(f"poll failed: {exc}")
            self._update(state="error", action="error", error=str(exc))

    def _wait_for_browser(self, timeout: float = 15.0) -> list[dict[str, Any]]:
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while not self._stop_event.is_set() and time.time() < deadline:
            try:
                browsers = bsk.browsers()
                if browsers:
                    return browsers
            except Exception as exc:
                last_error = exc
            if self._stop_event.wait(1.0):
                break
        if last_error:
            raise RuntimeError(f"BrowserSkill 连接失败: {last_error}")
        raise RuntimeError("没有连接到 BrowserSkill，请先打开浏览器扩展")

    def _evaluate(self, expression: str, timeout: int = 20, retries: int = 4) -> dict[str, Any]:
        if not self._session_id or not self._tab_id:
            raise RuntimeError("当前没有 BrowserSkill 会话")
        last_error: Exception | None = None
        for _ in range(retries):
            try:
                return bsk.run_json([
                    "evaluate",
                    "--session", self._session_id,
                    "--tab-id", self._tab_id,
                    "--json",
                    expression,
                ], timeout=timeout)
            except Exception as exc:
                last_error = exc
                if not _busy_error(exc):
                    raise
                if self._stop_event.wait(0.6):
                    raise
        raise last_error or RuntimeError("BrowserSkill 忙碌")

    def _command_start(self, payload: dict[str, Any]) -> None:
        if self._session_id:
            self._command_stop()
        config = load_config()
        previous_status = read_status()
        for key in ("course_url", "browser", "poll_seconds", "playback_rate", "resume_last", "keep_browser_awake"):
            if key in payload and payload[key] is not None:
                setattr(config, key, payload[key])
        config = save_config(config)
        if not config.course_url:
            raise RuntimeError("请填写课程详情页地址")

        self._update(state="starting", action="waiting-browser", course_url=config.course_url, error=None)
        browsers = self._wait_for_browser(15.0)
        args = ["session", "start", "--json", "--name", config.session_name]
        if config.browser:
            args.extend(["--browser", config.browser])
        session = bsk.run_json(args, timeout=30)
        session_id = str(session.get("session_id") or session.get("sessionId") or "")
        if not session_id:
            raise RuntimeError("BrowserSkill 未返回 session_id")
        self._owns_session = True
        self._session_id = session_id

        try:
            tab = bsk.run_json([
                "tab", "create",
                "--session", session_id,
                "--url", config.course_url,
                "--json",
            ], timeout=30)
            self._tab_id = str(tab.get("tab_id") or "")
            if not self._tab_id:
                raise RuntimeError("BrowserSkill 未返回 tab_id")
        except Exception:
            self._command_stop()
            raise

        now = time.time()
        self._loading_until = 0.0
        self._next_recovery_at = 0.0
        self._pending_resource_index = 0
        self._pending_recovery_attempts = 0
        self._reset_progress_watchdog(0.0, 0, now, grace=20.0)
        self._next_recovery_at = now + 5.0
        self._update(
            state="running",
            action="starting",
            lesson="",
            resourceIndex=0,
            resourceCount=0,
            currentTime=0.0,
            duration=0.0,
            progressPct=0.0,
            paused=None,
            session_id=session_id,
            tab_id=self._tab_id,
            browser_id=str(browsers[0].get("instance_id") or ""),
            course_url=config.course_url,
            error=None,
        )
        try:
            bsk.resize_window(session_id, 1200, 800)
        except Exception as exc:
            self._log(f"resize agent window failed: {exc}")
        self._log(f"GUI controller started session={session_id} tab={self._tab_id}")
        if config.resume_last and str(previous_status.get("course_url") or "") == config.course_url:
            self._resume_saved_position(previous_status)
        else:
            self._wait_and_poll(1.0)

    def _resume_saved_position(self, previous: dict[str, Any]) -> None:
        try:
            index = int(previous.get("resourceIndex") or 0)
            current_time = float(previous.get("currentTime") or 0)
        except (TypeError, ValueError):
            self._wait_and_poll(1.0)
            return
        if index <= 0:
            self._wait_and_poll(1.0)
            return
        self._update(action="restoring", lesson=str(previous.get("lesson") or ""))
        now = time.time()
        self._pending_resource_index = 0
        self._pending_recovery_attempts = 0
        self._reset_progress_watchdog(current_time, index, now, grace=20.0)
        self._next_recovery_at = now + 2.0
        try:
            result = self._evaluate(render_resume_expression(index, current_time), timeout=35, retries=3)
            value = result.get("value") or {}
            self._log(
                f"resume saved position index={index} saved={current_time:.2f} "
                f"actual={value.get('currentTime', 0):.2f} ok={value.get('ok')}"
            )
            if value.get("ok"):
                self._wait_and_poll(0.8)
                if bool(value.get("paused")):
                    self._recover_once()
            else:
                self._wait_and_poll(1.0)
        except Exception as exc:
            self._log(f"resume saved position failed: {exc}")
            self._wait_and_poll(1.0)

    def _command_stop(self) -> None:
        self._update(action="stopping")
        if self._owns_session and self._session_id:
            try:
                bsk.run(["session", "stop", self._session_id], timeout=25)
            except Exception:
                pass
        self._session_id = None
        self._tab_id = None
        self._owns_session = False
        self._recovery_attempts = 0
        self._reload_attempts = 0
        self._pending_resource_index = 0
        self._pending_recovery_attempts = 0
        self._stalled_since = None
        self._update(state="stopped", action="stopped", paused=None, session_id=None, tab_id=None)
        self._log("GUI controller stopped")

    def _wait_and_poll(self, seconds: float) -> None:
        if not self._stop_event.wait(seconds):
            self._safe_poll()

    def _poll(self) -> None:
        if not self._session_id or not self._tab_id:
            return
        config = load_config()
        payload = self._evaluate(render_expression(config.playback_rate), timeout=25)
        value = payload.get("value") or {}
        action = str(value.get("action") or "unknown")
        current_time = float(value.get("currentTime") or 0)
        duration = float(value.get("duration") or 0)
        progress = (current_time / duration * 100.0) if duration > 0 else 0.0
        state = {
            "state": "complete" if action == "complete" else "running",
            "action": action,
            "lesson": str(value.get("lesson") or ""),
            "pageTitle": str(value.get("title") or ""),
            "next": str(value.get("nextLesson") or value.get("nextSection") or ""),
            "resourceIndex": int(value.get("resourceIndex") or 0),
            "resourceCount": int(value.get("resourceCount") or 0),
            "currentTime": current_time,
            "duration": duration,
            "progressPct": progress,
            "paused": value.get("paused"),
            "ended": bool(value.get("ended")),
            "playbackRate": float(value.get("playbackRate") or config.playback_rate),
            "session_id": self._session_id,
            "tab_id": self._tab_id,
            "error": None,
            "hidden": bool(value.get("hidden")) if "hidden" in value else None,
            "visibility": value.get("visibility"),
            "viewportWidth": value.get("viewportWidth"),
            "viewportHeight": value.get("viewportHeight"),
            "readyState": int(value.get("readyState") or 0),
        }
        self._update(**state)

        try:
            width = int(value.get("viewportWidth") or 0)
            height = int(value.get("viewportHeight") or 0)
        except (TypeError, ValueError):
            width = height = 0
        if load_config().keep_browser_awake and width and height and (width < 900 or height < 600):
            self._log(f"agent window too small {width}x{height}; resizing")
            try:
                bsk.resize_window(self._session_id, 1200, 800)
            except Exception as exc:
                self._log(f"resize agent window failed: {exc}")

        now = time.time()
        keep_awake = load_config().keep_browser_awake
        resource_index = state["resourceIndex"]
        previous_index = self._last_resource_index
        resource_changed = resource_index > 0 and previous_index != resource_index
        rewound = self._last_current_time > 0 and current_time + 1.0 < self._last_current_time
        switching = action in {"next-resource", "skip-completed"}
        next_resource_index = int(value.get("nextResourceIndex") or 0)
        if switching and next_resource_index > 0:
            if self._pending_resource_index != next_resource_index:
                self._pending_recovery_attempts = 0
                self._log(f"next resource target set to {next_resource_index}")
            self._pending_resource_index = next_resource_index

        if switching:
            # The DOM can keep reporting the previous video for a short time
            # while the new resource loads. Never compare both timelines.
            self._reset_progress_watchdog(0.0, None, now, grace=20.0)
        elif resource_changed:
            reason = ""
            if previous_index > 0:
                reason = (
                    f"resource changed {previous_index}->{resource_index}; "
                    "resetting progress watchdog"
                )
            self._reset_progress_watchdog(current_time, resource_index, now, grace=10.0, reason=reason)
        elif rewound:
            self._reset_progress_watchdog(
                current_time,
                resource_index,
                now,
                grace=8.0,
                reason=f"playback position moved backwards to {current_time:.2f}; resetting progress watchdog",
            )

        if resource_changed and self._pending_resource_index == resource_index:
            self._log(f"pending resource {resource_index} loaded; watchdog baseline updated")
            self._pending_resource_index = 0
            self._pending_recovery_attempts = 0

        pending = self._pending_resource_index
        pending_mismatch = pending > 0 and resource_index > 0 and resource_index != pending
        if pending_mismatch and now >= self._loading_until and now >= self._next_recovery_at:
            self._recover_pending_resource()
            return

        advanced = current_time > self._last_current_time + 0.15 and not switching
        if action in {"playing", "resume"} and not state["paused"] and advanced:
            self._last_current_time = current_time
            if resource_index > 0:
                self._last_resource_index = resource_index
            self._last_progress_time = now
            if self._recovery_attempts and current_time > self._recovery_anchor_current + 2.0:
                self._log("playback recovered and progress is stable")
                self._recovery_attempts = 0
                self._reload_attempts = 0
                self._stalled_since = None
            elif not self._recovery_attempts:
                self._stalled_since = None
        elif action in {"playing", "resume"} and not state["paused"] and keep_awake:
            if now < self._loading_until:
                self._stalled_since = None
            elif self._stalled_since is None:
                self._stalled_since = now
            elif now - self._stalled_since >= 5.0 and now >= self._next_recovery_at:
                self._log(
                    f"progress stalled at index={resource_index} time={current_time:.2f}; "
                    "attempting a gentle browser recovery"
                )
                self._recover_once(allow_reload=False)
                self._stalled_since = now
        elif action in {"wait-video", "wait-player"}:
            if now >= self._loading_until and now >= self._next_recovery_at:
                if self._pending_resource_index > 0:
                    self._log(
                        f"video load wait exceeded; restoring pending resource "
                        f"{self._pending_resource_index}"
                    )
                    self._recover_pending_resource()
                elif self._reload_attempts < 1:
                    self._log("video load wait exceeded; checking browser/page")
                    self._recover_once(allow_reload=True)
                else:
                    self._next_recovery_at = now + 30.0
        elif action == "needs-user-gesture":
            if now >= self._next_recovery_at:
                self._recover_once(allow_reload=False)
        elif action == "loading-catalog":
            self._stalled_since = None

        if action == "complete":
            self._log("course complete")
            if self._owns_session:
                try:
                    bsk.run(["session", "stop", self._session_id], timeout=25)
                except Exception:
                    pass
            self._session_id = None
            self._tab_id = None
            self._owns_session = False
            self._pending_resource_index = 0
            self._pending_recovery_attempts = 0
            self._update(state="complete", action="complete")

    def _recover_pending_resource(self) -> None:
        pending = self._pending_resource_index
        if not self._session_id or not self._tab_id or pending <= 0:
            return
        now = time.time()
        if now < self._next_recovery_at:
            return
        self._pending_recovery_attempts += 1
        state = self.snapshot()
        self._log(
            f"pending resource recovery attempt {self._pending_recovery_attempts}: "
            f"current={state.get('resourceIndex')} target={pending}"
        )
        try:
            bsk.run(["tab", "select", "--session", self._session_id, self._tab_id], timeout=15)
        except Exception:
            pass
        activate_browser(title_hint=str(state.get("pageTitle") or state.get("lesson") or ""))
        try:
            payload = self._evaluate(render_resume_expression(pending, 0.0), timeout=35, retries=3)
            result = payload.get("value") or {}
            self._log(
                "pending resource recovery result: "
                f"ok={result.get('ok')}, reason={result.get('reason')}, "
                f"target={result.get('targetIndex')}, current={result.get('currentIndex')}, "
                f"paused={result.get('paused')}"
            )
            if result.get("reason") in {"platform-ahead", "all-completed"}:
                self._pending_resource_index = 0
                self._pending_recovery_attempts = 0
        except Exception as exc:
            self._log(f"pending resource recovery failed: {exc}")
        self._loading_until = max(self._loading_until, now + 12.0)
        self._next_recovery_at = now + 10.0

    def _recover_once(self, allow_reload: bool = False) -> None:
        if not self._session_id or not self._tab_id:
            return
        now = time.time()
        if now < self._next_recovery_at:
            return
        self._recovery_attempts += 1
        attempt = self._recovery_attempts
        if attempt == 1:
            self._recovery_anchor_current = self._last_current_time
        state = self.snapshot()
        title_hint = str(state.get("pageTitle") or state.get("lesson") or "")
        self._log(
            f"gentle recovery attempt {attempt} "
            f"(index={state.get('resourceIndex')}, time={state.get('currentTime')}, "
            f"paused={state.get('paused')}, ready={state.get('readyState')})"
        )
        try:
            bsk.run(["tab", "select", "--session", self._session_id, self._tab_id], timeout=15)
        except Exception:
            pass
        activate_browser(title_hint=title_hint)

        def reload_once() -> bool:
            if not allow_reload or self._reload_attempts >= 1:
                return False
            self._reload_attempts += 1
            self._log("video still unavailable; reloading page once")
            bsk.reload(self._session_id, self._tab_id)
            self._recovery_attempts = 0
            self._loading_until = now + 25.0
            self._next_recovery_at = now + 15.0
            return True

        try:
            if attempt == 1:
                payload = self._evaluate(PLAYBACK_RECOVERY_EXPRESSION, timeout=20, retries=3)
                value = payload.get("value") or {}
                self._log(
                    "gentle recovery result: "
                    f"reason={value.get('reason')}, time={value.get('currentTime')}, "
                    f"paused={value.get('paused')}, ready={value.get('readyState')}, "
                    f"error={value.get('playError') or value.get('error')}"
                )
                if not value.get("ok") and reload_once():
                    return
            elif attempt == 2:
                clicked = False
                for selector in (
                    "button.vjs-big-play-button",
                    "button.vjs-play-control",
                    '[aria-label="播放"]',
                    '[aria-label="播放视频"]',
                ):
                    try:
                        bsk.run([
                            "click", "--selector", selector,
                            "--session", self._session_id, "--tab-id", self._tab_id,
                        ], timeout=15)
                        clicked = True
                        break
                    except Exception:
                        continue
                if not clicked:
                    self._evaluate(PLAYBACK_RECOVERY_EXPRESSION, timeout=20, retries=2)
            elif reload_once():
                return
            else:
                self._log("gentle recovery ineffective; preserving page and rechecking later")
                self._recovery_attempts = 0
                self._loading_until = now + 10.0
                self._next_recovery_at = now + 30.0
                return
        except Exception as exc:
            self._log(f"gentle recovery failed: {exc}")
        self._loading_until = max(self._loading_until, now + 8.0)
        self._next_recovery_at = now + 8.0

    def _command_toggle(self) -> None:
        if not self._session_id:
            raise RuntimeError("课程尚未启动")
        payload = self._evaluate(PLAYBACK_TOGGLE_EXPRESSION, timeout=20)
        value = payload.get("value") or {}
        if value.get("reason") == "blocked":
            self._recovery_attempts = 0
            self._recover_once()
        self._wait_and_poll(0.5)

    def _command_switch(self, direction: str) -> None:
        if not self._session_id:
            raise RuntimeError("课程尚未启动")
        expression = NEXT_VIDEO_EXPRESSION if direction == "next" else PREVIOUS_VIDEO_EXPRESSION
        payload = self._evaluate(expression, timeout=20)
        value = payload.get("value") or {}
        if not value.get("ok"):
            self._update(action=value.get("reason") or "switch-failed")
            return
        self._update(
            action="switching-next" if direction == "next" else "switching-previous",
            lesson=str(value.get("to") or ""),
        )
        now = time.time()
        if direction == "next":
            target = int(value.get("nextIndex") or 0)
            self._pending_resource_index = target
        else:
            self._pending_resource_index = 0
        self._pending_recovery_attempts = 0
        self._reset_progress_watchdog(0.0, None, now, grace=20.0)
        self._next_recovery_at = now + 2.0
        self._wait_and_poll(0.8)
