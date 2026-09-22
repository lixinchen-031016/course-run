from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from . import __version__
from .config import load_config, paths, save_config
from .manager import get_doctor_report, get_logs, next_video, open_data_directory, start_course, status, stop_course
from .worker import run_worker


def _status_text(value: dict[str, Any]) -> str:
    count = value.get("resourceCount") or 0
    index = value.get("resourceIndex") or 0
    progress = float(value.get("progressPct") or 0)
    lines = [
        f"状态: {value.get('state') or 'idle'}",
        f"动作: {value.get('action') or '-'}",
        f"课程: {value.get('lesson') or '-'}",
        f"进度: {f'{index}/{count}' if count else '-'}",
        f"播放: {progress:.2f}%",
        f"PID: {value.get('pid') or '-'} ({'running' if value.get('pid_running') else 'stopped'})",
        f"Session: {value.get('session_id') or '-'}",
        f"Tab: {value.get('tab_id') or '-'}",
        f"更新时间: {value.get('updated_at') or '-'}",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="course-run", description="跨平台 BrowserSkill 课程自动播放器")
    parser.add_argument("--version", action="version", version=f"course-run {__version__}")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="打开桌面小程序")
    gui.set_defaults(command="gui")

    start = sub.add_parser("start", help="启动课程后台播放")
    start.add_argument("--url", "--course-url", dest="course_url")
    start.add_argument("--browser", default=None)
    start.add_argument("--poll", type=int, default=None)
    start.add_argument("--playback-rate", type=float, default=None)
    start.add_argument("--session", default=None, help="附加到已有 BrowserSkill 会话")

    stop = sub.add_parser("stop", help="停止课程播放")
    stop.add_argument("--keep-session", action="store_true")

    status_parser = sub.add_parser("status", help="查看状态")
    status_parser.add_argument("--json", action="store_true")

    logs = sub.add_parser("logs", help="查看日志")
    logs.add_argument("--lines", type=int, default=120)

    next_parser = sub.add_parser("next", help="立即切换到下一个视频")
    next_parser.add_argument("--session", default=None, help="BrowserSkill 会话 ID（默认读取当前任务）")
    next_parser.add_argument("--tab", default=None, help="BrowserSkill 标签 ID（默认读取当前任务）")

    sub.add_parser("doctor", help="检查 Node/Tk/bsk 与浏览器连接")
    sub.add_parser("open-logs", help="打开数据目录")

    worker = sub.add_parser("worker", help=argparse.SUPPRESS)
    worker.add_argument("--state", required=True)
    worker.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--worker-state" in argv:
        index = argv.index("--worker-state")
        state_path = pathlib.Path(argv[index + 1])
        run_worker(state_path, once=False)
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "gui"

    if command == "gui":
        from .gui import launch_gui
        launch_gui()
        return 0

    if command == "start":
        result = start_course(
            course_url=args.course_url,
            browser=args.browser,
            poll_seconds=args.poll,
            playback_rate=args.playback_rate,
            session_id=args.session,
        )
        print(f"已启动: PID {result['pid']}")
        print(f"Session: {result['session_id']}")
        print(f"Tab: {result['tab_id']}")
        print(f"数据目录: {paths().root}")
        print(_status_text(status()))
        return 0

    if command == "stop":
        result = stop_course(keep_session=args.keep_session)
        print("已停止" if result["ok"] else "停止请求已发送，但进程可能仍在退出")
        return 0

    if command == "status":
        value = status()
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(_status_text(value))
        return 0

    if command == "logs":
        result = get_logs(args.lines)
        print(result["worker"] or "暂无日志")
        if result["stderr"]:
            print("\n--- stderr ---")
            print(result["stderr"])
        return 0

    if command == "next":
        result = next_video(session_id=args.session, tab_id=args.tab)
        if result.get("ok"):
            print(f"已切换: {result.get('from')} -> {result.get('to')}")
        elif result.get("reason") == "at-end":
            print("当前已经是最后一个视频")
        else:
            print(f"切换失败: {result.get('reason') or result}")
        return 0 if result.get("ok") or result.get("reason") == "at-end" else 1

    if command == "doctor":
        report = get_doctor_report()
        print(f"BrowserSkill: {report['version']}")
        print(report["doctor"].get("stdout") or report["doctor"].get("stderr") or "")
        if report.get("browser_error"):
            print(f"浏览器检测失败: {report['browser_error']}")
        else:
            print(f"已连接浏览器: {len(report.get('browsers') or [])}")
        return 0

    if command == "open-logs":
        print(f"数据目录: {paths().root}")
        open_data_directory()
        return 0

    if command == "worker":
        run_worker(pathlib.Path(args.state), once=args.once)
        return 0

    parser.print_help()
    return 1
