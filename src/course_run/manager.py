from __future__ import annotations

import os
import pathlib
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from . import bsk
from .expression import NEXT_VIDEO_EXPRESSION, render_expression
from .config import (
    Config,
    clear_state,
    load_config,
    load_state,
    paths,
    read_status,
    remove_stop_flag,
    request_stop,
    save_config,
    save_state,
    write_status,
)
from .platform_adapter import detached_kwargs, open_path, pid_running, terminate_pid, worker_command


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def session_id_from(value: dict[str, Any]) -> str:
    return str(value.get("session_id") or value.get("sessionId") or value.get("id") or "")


def tail(path: pathlib.Path, lines: int = 120) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-max(1, lines):])
    except OSError:
        return ""


def get_doctor_report() -> dict[str, Any]:
    report: dict[str, Any] = {"version": "", "doctor": {}, "browsers": []}
    report["version"] = bsk.version()
    diagnostic = bsk.doctor()
    report["doctor"] = {
        "ok": diagnostic.code == 0,
        "stdout": diagnostic.stdout,
        "stderr": diagnostic.stderr,
    }
    try:
        report["browsers"] = bsk.browsers()
    except Exception as exc:
        report["browser_error"] = str(exc)
    return report


def start_course(
    course_url: str | None = None,
    browser: str | None = None,
    poll_seconds: int | None = None,
    playback_rate: float | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if course_url is not None:
        updates["course_url"] = course_url
    if browser is not None:
        updates["browser"] = browser
    if poll_seconds is not None:
        updates["poll_seconds"] = poll_seconds
    if playback_rate is not None:
        updates["playback_rate"] = playback_rate
    config = save_config(**updates)
    if not config.course_url:
        raise RuntimeError("请填写课程详情页地址")

    old_state = load_state()
    if old_state and pid_running(int(old_state.get("pid") or 0)):
        raise RuntimeError(f"课程任务已在运行，PID={old_state.get('pid')}")
    if old_state and old_state.get("owns_session") and old_state.get("session_id"):
        try:
            bsk.run(["session", "stop", str(old_state["session_id"])], timeout=20)
        except Exception:
            pass
        clear_state()

    browsers = bsk.browsers()
    if not browsers:
        raise RuntimeError("没有连接到 BrowserSkill。请先打开 Edge/Chrome 和 BrowserSkill 扩展")

    owns_session = False
    if not session_id:
        args = ["session", "start", "--json", "--name", config.session_name]
        if config.browser:
            args.extend(["--browser", config.browser])
        session = bsk.run_json(args, timeout=30)
        session_id = session_id_from(session)
        if not session_id:
            raise RuntimeError("BrowserSkill 未返回 session_id")
        owns_session = True

    p = paths()
    remove_stop_flag()
    try:
        tab = bsk.run_json([
            "tab", "create",
            "--session", session_id,
            "--url", config.course_url,
            "--json",
        ], timeout=30)
        tab_id = str(tab.get("tab_id") or "")
        if not tab_id:
            raise RuntimeError("BrowserSkill 未返回 tab_id")

        state = {
            "pid": None,
            "session_id": session_id,
            "tab_id": tab_id,
            "owns_session": owns_session,
            "course_url": config.course_url,
            "browser_id": str(browsers[0].get("instance_id") or ""),
            "poll_seconds": config.poll_seconds,
            "switch_delay_seconds": config.switch_delay_seconds,
            "retry_limit": config.retry_limit,
            "playback_rate": config.playback_rate,
            "started_at": utc_now(),
        }
        save_state(state)
        write_status({**state, "state": "starting", "action": "starting", "updated_at": utc_now()})

        p.root.mkdir(parents=True, exist_ok=True)
        with p.log.open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_now()} 启动课程 {config.course_url}\n")
        with p.stdout.open("ab") as stdout, p.stderr.open("ab") as stderr:
            process = subprocess.Popen(
                worker_command(p.state),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                cwd=str(p.root),
                **detached_kwargs(),
            )
        state["pid"] = process.pid
        save_state(state)
        time.sleep(1.8)
        if process.poll() is not None:
            error = tail(p.stderr, 40) or tail(p.log, 40)
            raise RuntimeError(f"后台任务启动失败：{error}")
        return {**state, "status": read_status()}
    except Exception:
        if owns_session and session_id:
            try:
                bsk.run(["session", "stop", session_id], timeout=20)
            except Exception:
                pass
        clear_state()
        raise


def _is_busy_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in (
        "session_busy",
        "unfinished command",
        "already has an unfinished",
    ))


def _evaluate_with_retry(expression: str, session_id: str, tab_id: str, attempts: int = 5):
    last_error: Exception | None = None
    for index in range(attempts):
        try:
            return bsk.run_json([
                "evaluate",
                "--session", session_id,
                "--tab-id", tab_id,
                "--json",
                expression,
            ], timeout=35)
        except Exception as exc:
            last_error = exc
            if not _is_busy_error(exc) or index + 1 >= attempts:
                raise
            time.sleep(1.0)
    raise last_error or RuntimeError("BrowserSkill 状态检查失败")


def next_video(session_id: str | None = None, tab_id: str | None = None, resume: bool = True) -> dict[str, Any]:
    state = load_state() or {}
    session = str(session_id or state.get("session_id") or "")
    tab = str(tab_id or state.get("tab_id") or "")
    if not session or not tab:
        raise RuntimeError("当前没有可控制的 BrowserSkill 会话")

    result = _evaluate_with_retry(NEXT_VIDEO_EXPRESSION, session, tab)
    value = result.get("value") or {}
    if not value.get("ok"):
        return value

    if resume:
        playback_rate = float(state.get("playback_rate") or load_config().playback_rate)
        expression = render_expression(playback_rate)
        for _ in range(4):
            time.sleep(1.5)
            try:
                probe = _evaluate_with_retry(expression, session, tab)
            except Exception:
                break
            action = ((probe.get("value") or {}).get("action") or "")
            if action == "dismissed-modal":
                continue
            if action == "needs-user-gesture":
                try:
                    bsk.run([
                        "click", "--selector", "video",
                        "--session", session, "--tab-id", tab,
                    ], timeout=30)
                except Exception:
                    pass
                continue
            if action in {"resume", "playing"}:
                break

    value["session_id"] = session
    value["tab_id"] = tab
    return value


def stop_course(keep_session: bool = False) -> dict[str, Any]:
    state = load_state()
    pid = int(state.get("pid") or 0) if state else 0
    graceful = True
    if pid_running(pid):
        request_stop()
        deadline = time.time() + 12
        while time.time() < deadline:
            if not pid_running(pid):
                break
            time.sleep(0.5)
        if pid_running(pid):
            graceful = terminate_pid(pid)

    if not keep_session and state and state.get("owns_session") and state.get("session_id"):
        try:
            bsk.run(["session", "stop", str(state["session_id"])], timeout=20)
        except Exception:
            pass

    remove_stop_flag()
    clear_state()
    write_status({
        "state": "stopped",
        "action": "stopped",
        "session_id": state.get("session_id") if state else None,
        "tab_id": state.get("tab_id") if state else None,
        "updated_at": utc_now(),
    })
    return {"ok": graceful, "state": state}


def status() -> dict[str, Any]:
    state = load_state() or {}
    current = read_status()
    pid = int(state.get("pid") or current.get("pid") or 0)
    return {
        **current,
        "pid": pid or None,
        "pid_running": pid_running(pid),
        "session_id": state.get("session_id") or current.get("session_id"),
        "tab_id": state.get("tab_id") or current.get("tab_id"),
        "course_url": state.get("course_url"),
        "owns_session": bool(state.get("owns_session")),
    }


def get_logs(lines: int = 120) -> dict[str, str]:
    p = paths()
    return {
        "worker": tail(p.log, lines),
        "stdout": tail(p.stdout, lines),
        "stderr": tail(p.stderr, lines),
    }


def open_data_directory() -> bool:
    return open_path(paths().root)
