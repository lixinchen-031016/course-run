from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from .platform_adapter import app_data_dir, ensure_dir


class InstanceLock:
    """A per-user process lock that is released automatically on exit."""

    def __init__(self, path: Path, handle: BinaryIO) -> None:
        self.path = path
        self._handle: BinaryIO | None = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            handle.close()

    def __del__(self) -> None:
        self.release()


def acquire_instance_lock(path: Path | None = None) -> InstanceLock | None:
    """Return a lock, or None when another CourseRun instance owns it."""
    lock_path = path or (app_data_dir() / "course-run.lock")
    ensure_dir(lock_path.parent)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return InstanceLock(lock_path, handle)


def show_already_running() -> None:
    message = "CourseRun 已经在运行。\n\n请切换到现有窗口，不要同时启动多个实例。"
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        messagebox.showinfo("CourseRun", message)
        root.destroy()
    except Exception:
        print(message)
