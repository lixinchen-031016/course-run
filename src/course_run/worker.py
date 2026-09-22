from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from . import bsk
from .config import clear_state, load_config, paths, stop_requested, write_status
from .platform_adapter import activate_browser
from .expression import render_expression


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_log(message: str) -> None:
    p = paths()
    p.root.mkdir(parents=True, exist_ok=True)
    with p.log.open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} {message}\n")


def stop_session(session_id: str | None) -> None:
    if not session_id:
        return
    try:
        bsk.run(["session", "stop", session_id], timeout=25)
    except Exception as exc:
        append_log(f"停止 BrowserSkill 会话失败: {exc}")


def recover_playback(session_id: str, tab_id: str, attempt: int) -> bool:
    activate_browser()
    try:
        bsk.run(["tab", "select", "--session", session_id, tab_id], timeout=20)
    except Exception:
        pass

    if attempt <= 1:
        bsk.run([
            "click", "--selector", "video",
            "--session", session_id, "--tab-id", tab_id,
        ], timeout=30)
        return False

    if attempt == 2:
        for selector in ('[aria-label="播放"]', '[aria-label="播放视频"]', "video"):
            try:
                bsk.run([
                    "click", "--selector", selector,
                    "--session", session_id, "--tab-id", tab_id,
                ], timeout=20)
                return False
            except Exception:
                continue
        return False

    append_log("多次恢复失败，重新加载课程页面")
    bsk.reload(session_id, tab_id)
    return True


def run_worker(state_path: pathlib.Path, once: bool = False) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    config = load_config()
    if state.get("config"):
        config = config.from_dict({**asdict(config), **state["config"]})
        config.normalized()

    session_id = str(state.get("session_id") or "")
    tab_id = str(state.get("tab_id") or "")
    owns_session = bool(state.get("owns_session"))
    poll_seconds = max(2, int(state.get("poll_seconds") or config.poll_seconds))
    switch_delay_seconds = max(1, int(state.get("switch_delay_seconds") or config.switch_delay_seconds))
    retry_limit = max(1, int(state.get("retry_limit") or config.retry_limit))
    playback_rate = float(state.get("playback_rate") or config.playback_rate)
    expression = render_expression(playback_rate)

    if not session_id or not tab_id:
        raise RuntimeError("后台任务缺少 BrowserSkill session_id 或 tab_id")

    append_log(f"后台任务启动 PID={os.getpid()} session={session_id} tab={tab_id}")
    write_status({
        "state": "starting",
        "action": "starting",
        "session_id": session_id,
        "tab_id": tab_id,
        "started_at": utc_now(),
    })

    consecutive_errors = 0
    recovery_attempts = 0
    last_action = ""
    last_lesson = ""
    last_bucket = ""

    while True:
        if stop_requested():
            append_log("收到停止请求")
            if owns_session:
                stop_session(session_id)
            write_status({
                "state": "stopped",
                "action": "stopped",
                "session_id": session_id,
                "tab_id": tab_id,
                "updated_at": utc_now(),
            })
            clear_state()
            return

        try:
            payload = bsk.run_json([
                "evaluate",
                "--session", session_id,
                "--tab-id", tab_id,
                "--json",
                expression,
            ], timeout=35)
            value = payload.get("value") or {}
            action = str(value.get("action") or "unknown")
            lesson = str(value.get("lesson") or "")
            resource_index = int(value.get("resourceIndex") or 0)
            resource_count = int(value.get("resourceCount") or 0)
            current_time = float(value.get("currentTime") or 0)
            duration = float(value.get("duration") or 0)
            paused = bool(value.get("paused"))
            ended = bool(value.get("ended"))
            progress = (current_time / duration * 100.0) if duration > 0 else 0.0
            next_lesson = str(value.get("nextLesson") or value.get("nextSection") or "")
            bucket = str(int(current_time // 300))

            if action == "needs-user-gesture":
                recovery_attempts += 1
                append_log(f"自动播放受限，执行恢复尝试 {recovery_attempts} ({resource_index}/{resource_count})")
                try:
                    if recover_playback(session_id, tab_id, recovery_attempts):
                        recovery_attempts = 0
                except Exception as exc:
                    append_log(f"恢复操作失败: {exc}")

            status: dict[str, Any] = {
                "state": "complete" if action == "complete" else "running",
                "action": action,
                "lesson": lesson,
                "next": next_lesson,
                "resourceIndex": resource_index,
                "resourceCount": resource_count,
                "currentTime": current_time,
                "duration": duration,
                "progressPct": progress,
                "paused": paused,
                "ended": ended,
                "playbackRate": float(value.get("playbackRate") or playback_rate),
                "session_id": session_id,
                "tab_id": tab_id,
                "pid": os.getpid(),
                "updated_at": utc_now(),
            }
            write_status(status)

            should_log = lesson != last_lesson or action != last_action or bucket != last_bucket
            if should_log:
                suffix = f" ({resource_index}/{resource_count})" if resource_count else ""
                arrow = f" -> {next_lesson}" if next_lesson else ""
                append_log(f"{action}: {lesson}{suffix} {progress:.2f}%{arrow}")
                last_action, last_lesson, last_bucket = action, lesson, bucket

            if action == "complete":
                append_log(f"课程播放完成: {lesson}")
                if owns_session:
                    stop_session(session_id)
                write_status({**status, "state": "complete", "updated_at": utc_now()})
                clear_state()
                return

            consecutive_errors = 0
            if action not in {"needs-user-gesture", "wait-player", "wait-video"}:
                recovery_attempts = 0
            if once:
                return
            if action == "next-resource":
                time.sleep(switch_delay_seconds)
            elif action == "dismissed-modal":
                time.sleep(2)
            elif action == "needs-user-gesture":
                time.sleep(5)
            else:
                time.sleep(poll_seconds)
        except Exception as exc:
            consecutive_errors += 1
            append_log(f"检查失败 ({consecutive_errors}/{retry_limit}): {exc}")
            if consecutive_errors >= retry_limit:
                write_status({
                    "state": "error",
                    "action": "error",
                    "session_id": session_id,
                    "tab_id": tab_id,
                    "error": str(exc),
                    "updated_at": utc_now(),
                })
                return
            time.sleep(poll_seconds)
