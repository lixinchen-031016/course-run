from __future__ import annotations

import platform
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

from .config import Config, load_config, paths, save_config
from .manager import get_doctor_report, get_logs, next_video, open_data_directory, start_course, status, stop_course


class CourseRunApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("课程自动播放器")
        self.root.geometry("940x680")
        self.root.minsize(760, 560)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.last_logs = ""

        self.course_url = tk.StringVar()
        self.session_name = tk.StringVar()
        self.browser_id = tk.StringVar()
        self.poll_seconds = tk.IntVar()
        self.playback_rate = tk.DoubleVar()
        self.status_state = tk.StringVar(value="idle")
        self.status_action = tk.StringVar(value="-")
        self.status_lesson = tk.StringVar(value="-")
        self.status_count = tk.StringVar(value="-")
        self.status_progress = tk.StringVar(value="0.00%")
        self.status_meta = tk.StringVar(value="等待任务")
        self.platform_text = tk.StringVar(value=f"系统: {platform.system()} {platform.machine()}")

        self._build()
        self._load()
        self.root.after(100, self._process_events)
        self.root.after(100, self._refresh)

    def _build(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="BrowserSkill 课程自动播放器", font=("", 18, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.platform_text).pack(side="right")

        metrics = ttk.Frame(container)
        metrics.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for index in range(4):
            metrics.columnconfigure(index, weight=1)
        self._metric(metrics, 0, "运行状态", self.status_state)
        self._metric(metrics, 1, "当前课程", self.status_count)
        self._metric(metrics, 2, "视频进度", self.status_progress)
        self._metric(metrics, 3, "当前动作", self.status_action)

        form = ttk.LabelFrame(container, text="课程设置", padding=14)
        form.grid(row=2, column=0, sticky="nsew", padx=(0, 9))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="课程地址").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.course_url).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="任务名称").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.session_name).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="浏览器 ID").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.browser_id).grid(row=2, column=1, sticky="ew", pady=6)

        options = ttk.Frame(form)
        options.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)
        ttk.Label(options, text="检查间隔（秒）").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(options, from_=2, to=120, textvariable=self.poll_seconds, width=8).grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(options, text="播放速度").grid(row=0, column=2, sticky="w")
        ttk.Combobox(options, textvariable=self.playback_rate, values=(0.5, 1.0, 1.25, 1.5, 2.0), state="readonly", width=8).grid(row=0, column=3, sticky="w", padx=8)

        actions = ttk.Frame(form)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.start_button = ttk.Button(actions, text="开始播放", command=self._start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="停止", command=self._stop)
        self.stop_button.pack(side="left", padx=8)
        self.next_button = ttk.Button(actions, text="下一个视频", command=self._next)
        self.next_button.pack(side="left", padx=8)
        ttk.Button(actions, text="环境诊断", command=self._doctor).pack(side="left", padx=8)
        ttk.Button(actions, text="打开日志目录", command=open_data_directory).pack(side="left", padx=8)

        current = ttk.LabelFrame(container, text="当前任务", padding=14)
        current.grid(row=2, column=1, sticky="nsew", padx=(9, 0))
        ttk.Label(current, textvariable=self.status_lesson, wraplength=300, font=("", 12, "bold")).pack(anchor="w", pady=(0, 10))
        self.progress = ttk.Progressbar(current, maximum=100)
        self.progress.pack(fill="x", pady=4)
        ttk.Label(current, textvariable=self.status_meta, wraplength=300).pack(anchor="w", pady=(8, 0))

        logs_frame = ttk.LabelFrame(container, text="运行日志", padding=8)
        logs_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        self.logs = scrolledtext.ScrolledText(logs_frame, height=16, wrap="word")
        self.logs.pack(fill="both", expand=True)
        self.logs.configure(state="disabled")

    def _metric(self, parent: ttk.Frame, column: int, label: str, value: tk.StringVar) -> None:
        frame = ttk.Frame(parent, padding=10)
        frame.grid(row=0, column=column, sticky="ew", padx=5)
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Label(frame, textvariable=value, font=("", 13, "bold")).pack(anchor="w", pady=(3, 0))

    def _load(self) -> None:
        config = load_config()
        self.course_url.set(config.course_url)
        self.session_name.set(config.session_name)
        self.browser_id.set(config.browser)
        self.poll_seconds.set(config.poll_seconds)
        self.playback_rate.set(config.playback_rate)

    def _config(self) -> Config:
        return Config(
            course_url=self.course_url.get().strip(),
            session_name=self.session_name.get().strip() or "课程自动播放",
            browser=self.browser_id.get().strip(),
            poll_seconds=int(self.poll_seconds.get() or 10),
            playback_rate=float(self.playback_rate.get() or 1.0),
        ).normalized()

    def _run_background(self, function: Callable[[], str]) -> None:
        self._set_buttons(False)
        def runner() -> None:
            try:
                self.events.put(("ok", function()))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=runner, daemon=True).start()

    def _start(self) -> None:
        config = self._config()
        if not config.course_url:
            messagebox.showwarning("缺少课程地址", "请先填写课程详情页地址。")
            return
        save_config(config)
        self._run_background(lambda: self._start_message(start_course(
            course_url=config.course_url,
            browser=config.browser,
            poll_seconds=config.poll_seconds,
            playback_rate=config.playback_rate,
        )))

    @staticmethod
    def _start_message(result: dict) -> str:
        return f"已启动，PID {result.get('pid')}，Session {result.get('session_id')}"

    def _stop(self) -> None:
        self._run_background(lambda: "已停止" if stop_course().get("ok") else "停止请求已发送")

    def _next(self) -> None:
        self._run_background(lambda: self._next_message(next_video()))

    @staticmethod
    def _next_message(result: dict) -> str:
        if result.get("ok"):
            return f"已切换：{result.get('from')} -> {result.get('to')}"
        if result.get("reason") == "at-end":
            return "当前已经是最后一个视频"
        return f"切换失败：{result.get('reason') or result}"

    def _doctor(self) -> None:
        def task() -> str:
            report = get_doctor_report()
            return f"BrowserSkill: {report['version']}\n\n{report['doctor'].get('stdout') or report['doctor'].get('stderr')}\n已连接浏览器: {len(report.get('browsers') or [])}"
        self._run_background(task)

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.start_button.configure(state=state)
        self.stop_button.configure(state=state)
        self.next_button.configure(state=state)

    def _process_events(self) -> None:
        while True:
            try:
                kind, message = self.events.get_nowait()
            except queue.Empty:
                break
            self._set_buttons(True)
            if kind == "error":
                messagebox.showerror("操作失败", message)
            else:
                messagebox.showinfo("课程自动播放器", message)
        self.root.after(100, self._process_events)

    def _refresh(self) -> None:
        try:
            value = status()
            self.status_state.set(str(value.get("state") or "idle"))
            self.status_action.set(str(value.get("action") or "-"))
            self.status_lesson.set(str(value.get("lesson") or "等待任务"))
            count = int(value.get("resourceCount") or 0)
            index = int(value.get("resourceIndex") or 0)
            self.status_count.set(f"{index}/{count}" if count else "-")
            progress = float(value.get("progressPct") or 0)
            self.status_progress.set(f"{progress:.2f}%")
            self.progress["value"] = max(0, min(100, progress))
            self.status_meta.set(f"PID {value.get('pid') or '-'} · Session {value.get('session_id') or '-'} · {value.get('updated_at') or ''}")
            logs = get_logs(160)
            combined = logs.get("worker") or ""
            if logs.get("stderr"):
                combined += "\n--- stderr ---\n" + logs["stderr"]
            if combined != self.last_logs:
                self.last_logs = combined
                self.logs.configure(state="normal")
                self.logs.delete("1.0", "end")
                self.logs.insert("end", combined or "暂无日志")
                self.logs.see("end")
                self.logs.configure(state="disabled")
            running = bool(value.get("pid_running"))
            self.stop_button.configure(state="normal" if running else "disabled")
            self.next_button.configure(state="normal" if running else "disabled")
        except Exception:
            pass
        self.root.after(1200, self._refresh)


def launch_gui() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    CourseRunApp(root)
    root.mainloop()
