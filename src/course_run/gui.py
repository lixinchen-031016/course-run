from __future__ import annotations

import platform
import queue
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

from .config import Config, load_config, paths, save_config
from .controller import CourseController


class CourseRunApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CourseRun 课程自动播放器")
        self.root.geometry("980x720")
        self.root.minsize(820, 620)

        self.update_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.last_log_text = ""
        self.last_state: dict[str, Any] = {}

        self.course_url = tk.StringVar()
        self.session_name = tk.StringVar(value="课程自动播放")
        self.browser_id = tk.StringVar()
        self.poll_seconds = tk.IntVar(value=2)
        self.playback_rate = tk.DoubleVar(value=1.0)
        self.auto_start = tk.BooleanVar(value=False)
        self.resume_last = tk.BooleanVar(value=True)
        self.keep_browser_awake = tk.BooleanVar(value=True)
        self.status_state = tk.StringVar(value="未启动")
        self.status_action = tk.StringVar(value="idle")
        self.status_lesson = tk.StringVar(value="填写课程地址后点击“开始播放”")
        self.status_index = tk.StringVar(value="-")
        self.status_progress = tk.StringVar(value="0.00%")
        self.status_time = tk.StringVar(value="00:00 / 00:00")
        self.status_connection = tk.StringVar(value=f"{platform.system()} · BrowserSkill")
        self.pause_text = tk.StringVar(value="暂停")

        self.controller = CourseController(on_update=self._enqueue_update)
        self.controller.start()

        self._build()
        self._load_config()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._process_updates)
        self.root.after(500, self._refresh_logs)
        if self._config().auto_start and self._config().course_url:
            self.root.after(800, self._start)

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=18)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="CourseRun 课程自动播放器", font=("", 20, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.status_connection).grid(row=0, column=1, sticky="e")

        metrics = ttk.Frame(main)
        metrics.grid(row=1, column=0, sticky="ew", pady=(14, 12))
        for index in range(4):
            metrics.columnconfigure(index, weight=1)
        self._metric(metrics, 0, "运行状态", self.status_state)
        self._metric(metrics, 1, "视频序号", self.status_index)
        self._metric(metrics, 2, "播放进度", self.status_progress)
        self._metric(metrics, 3, "当前动作", self.status_action)

        form = ttk.LabelFrame(main, text="课程设置", padding=14)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="课程详情页地址").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(form, textvariable=self.course_url).grid(row=0, column=1, columnspan=3, sticky="ew", pady=6)

        ttk.Label(form, text="任务名称").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(form, textvariable=self.session_name).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(form, text="浏览器 ID（可留空）").grid(row=1, column=2, sticky="e", padx=(12, 8), pady=6)
        ttk.Entry(form, textvariable=self.browser_id).grid(row=1, column=3, sticky="ew", pady=6)

        ttk.Label(form, text="检查间隔（秒）").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Spinbox(form, from_=1, to=10, textvariable=self.poll_seconds, width=10).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(form, text="播放速度").grid(row=2, column=2, sticky="e", padx=(12, 8), pady=6)
        ttk.Combobox(form, textvariable=self.playback_rate, values=(0.5, 1.0, 1.25, 1.5, 2.0), state="readonly", width=10).grid(row=2, column=3, sticky="w", pady=6)
        ttk.Checkbutton(form, text="恢复上次视频和播放位置", variable=self.resume_last).grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="浏览器最小化时自动恢复", variable=self.keep_browser_awake).grid(row=3, column=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="打开程序后自动开始", variable=self.auto_start).grid(row=3, column=3, sticky="w", pady=(6, 0))

        actions = ttk.Frame(main)
        actions.grid(row=3, column=0, sticky="ew", pady=14)
        for index in range(7):
            actions.columnconfigure(index, weight=1)
        self.start_button = ttk.Button(actions, text="开始播放", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=4, ipady=8)
        self.pause_button = ttk.Button(actions, textvariable=self.pause_text, command=self._toggle_pause)
        self.pause_button.grid(row=0, column=1, sticky="ew", padx=4, ipady=8)
        self.previous_button = ttk.Button(actions, text="上一视频", command=self._previous)
        self.previous_button.grid(row=0, column=2, sticky="ew", padx=4, ipady=8)
        self.next_button = ttk.Button(actions, text="下一视频", command=self._next)
        self.next_button.grid(row=0, column=3, sticky="ew", padx=4, ipady=8)
        self.stop_button = ttk.Button(actions, text="停止", command=self._stop)
        self.stop_button.grid(row=0, column=4, sticky="ew", padx=4, ipady=8)
        ttk.Button(actions, text="环境检测", command=self._doctor).grid(row=0, column=5, sticky="ew", padx=4, ipady=8)
        ttk.Button(actions, text="日志目录", command=self._open_logs).grid(row=0, column=6, sticky="ew", padx=4, ipady=8)

        current = ttk.LabelFrame(main, text="当前播放", padding=14)
        current.grid(row=4, column=0, sticky="ew")
        current.columnconfigure(0, weight=1)
        ttk.Label(current, textvariable=self.status_lesson, wraplength=900, font=("", 13, "bold")).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(current, maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(current, textvariable=self.status_time).grid(row=2, column=0, sticky="e")

        logs_frame = ttk.LabelFrame(main, text="实时日志", padding=8)
        logs_frame.grid(row=5, column=0, sticky="nsew", pady=(14, 0))
        main.rowconfigure(5, weight=1)
        self.logs = scrolledtext.ScrolledText(logs_frame, height=14, wrap="word")
        self.logs.pack(fill="both", expand=True)
        self.logs.configure(state="disabled")

        ttk.Label(main, text="快捷键：← 上一视频　→ 下一视频　空格 暂停/继续　Ctrl+Enter 开始").grid(row=6, column=0, sticky="w", pady=(10, 0))

    def _metric(self, parent: ttk.Frame, column: int, label: str, variable: tk.StringVar) -> None:
        frame = ttk.Frame(parent, padding=10)
        frame.grid(row=0, column=column, sticky="ew", padx=4)
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Label(frame, textvariable=variable, font=("", 13, "bold")).pack(anchor="w", pady=(3, 0))

    def _load_config(self) -> None:
        config = load_config()
        self.course_url.set(config.course_url)
        self.session_name.set(config.session_name)
        self.browser_id.set(config.browser)
        self.poll_seconds.set(max(1, min(10, config.poll_seconds)))
        self.playback_rate.set(config.playback_rate)
        self.auto_start.set(config.auto_start)
        self.resume_last.set(config.resume_last)
        self.keep_browser_awake.set(config.keep_browser_awake)

    def _config(self) -> Config:
        return Config(
            course_url=self.course_url.get().strip(),
            session_name=self.session_name.get().strip() or "课程自动播放",
            browser=self.browser_id.get().strip(),
            poll_seconds=max(1, min(10, int(self.poll_seconds.get() or 2))),
            playback_rate=float(self.playback_rate.get() or 1.0),
            auto_start=bool(self.auto_start.get()),
            resume_last=bool(self.resume_last.get()),
            keep_browser_awake=bool(self.keep_browser_awake.get()),
        ).normalized()

    def _start(self) -> None:
        config = self._config()
        if not config.course_url:
            messagebox.showwarning("缺少课程地址", "请先填写课程详情页地址。")
            return
        save_config(config)
        self.controller.submit(
            "start",
            course_url=config.course_url,
            browser=config.browser,
            poll_seconds=config.poll_seconds,
            playback_rate=config.playback_rate,
            resume_last=config.resume_last,
        )

    def _stop(self) -> None:
        self.controller.submit("stop")

    def _toggle_pause(self) -> None:
        self.controller.submit("toggle")

    def _previous(self) -> None:
        self.controller.submit("previous")

    def _next(self) -> None:
        self.controller.submit("next")

    def _doctor(self) -> None:
        try:
            from .manager import get_doctor_report
            report = get_doctor_report()
            messagebox.showinfo(
                "环境检测",
                f"BrowserSkill: {report['version']}\n\n"
                f"{report['doctor'].get('stdout') or report['doctor'].get('stderr')}\n"
                f"已连接浏览器: {len(report.get('browsers') or [])}",
            )
        except Exception as exc:
            messagebox.showerror("环境检测失败", str(exc))

    def _open_logs(self) -> None:
        from .platform_adapter import open_path
        open_path(paths().root)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Left>", lambda _event: self._previous())
        self.root.bind("<Right>", lambda _event: self._next())
        self.root.bind("<space>", lambda _event: self._toggle_pause())
        self.root.bind("<Control-Return>", lambda _event: self._start())

    def _enqueue_update(self, state: dict[str, Any]) -> None:
        self.update_queue.put(state)

    def _process_updates(self) -> None:
        changed = False
        while True:
            try:
                self.last_state = self.update_queue.get_nowait()
                changed = True
            except queue.Empty:
                break
        if changed:
            self._render_state(self.last_state)
        self.root.after(100, self._process_updates)

    def _render_state(self, value: dict[str, Any]) -> None:
        self.status_state.set(str(value.get("state") or "idle"))
        self.status_action.set(str(value.get("action") or "idle"))
        self.status_lesson.set(str(value.get("lesson") or "等待课程开始"))
        count = int(value.get("resourceCount") or 0)
        index = int(value.get("resourceIndex") or 0)
        self.status_index.set(f"{index}/{count}" if count else "-")
        progress = float(value.get("progressPct") or 0)
        self.status_progress.set(f"{progress:.2f}%")
        self.progress["value"] = max(0, min(100, progress))
        self.status_time.set(f"{self._format_time(value.get('currentTime'))} / {self._format_time(value.get('duration'))}")
        running = value.get("state") in {"running", "starting"} and bool(value.get("session_id"))
        for button in (self.pause_button, self.previous_button, self.next_button, self.stop_button):
            button.configure(state="normal" if running else "disabled")
        self.pause_text.set("继续" if value.get("paused") is True else "暂停")
        if value.get("error"):
            self.status_lesson.set(str(value["error"]))

    @staticmethod
    def _format_time(seconds: Any) -> str:
        try:
            total = max(0, int(float(seconds or 0)))
        except (TypeError, ValueError):
            total = 0
        return f"{total // 60:02d}:{total % 60:02d}"

    def _refresh_logs(self) -> None:
        try:
            content = paths().log.read_text(encoding="utf-8", errors="replace").splitlines()
            text = "\n".join(content[-120:])
        except OSError:
            text = ""
        if text != self.last_log_text:
            self.last_log_text = text
            self.logs.configure(state="normal")
            self.logs.delete("1.0", "end")
            self.logs.insert("end", text or "暂无日志")
            self.logs.see("end")
            self.logs.configure(state="disabled")
        self.root.after(800, self._refresh_logs)

    def _on_close(self) -> None:
        state = self.controller.snapshot()
        running = state.get("state") in {"running", "starting"}
        if running and not messagebox.askyesno("退出 CourseRun", "退出程序会停止课程播放，确定退出吗？"):
            return
        self.controller.shutdown(stop_session=True)
        self.root.destroy()


def launch_gui() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    CourseRunApp(root)
    root.mainloop()
