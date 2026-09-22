from __future__ import annotations

import ctypes
import os
import pathlib
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass


def system_name() -> str:
    value = platform.system().lower()
    if value.startswith("win"):
        return "windows"
    if value == "darwin":
        return "macos"
    return "linux"


def app_data_dir() -> pathlib.Path:
    system = system_name()
    home = pathlib.Path.home()
    if system == "windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return pathlib.Path(base or home) / "CourseRun"
    if system == "macos":
        return home / "Library" / "Application Support" / "CourseRun"
    return pathlib.Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "course-run"


def ensure_dir(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def detached_kwargs() -> dict:
    if system_name() == "windows":
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flags, "close_fds": True}
    return {"start_new_session": True, "close_fds": True}


def pid_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if system_name() != "windows":
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def terminate_pid(pid: int | None) -> bool:
    if not pid_running(pid):
        return True
    try:
        if system_name() == "windows":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.kill(pid, 15)
    except OSError:
        pass
    return not pid_running(pid)


def bsk_candidates() -> list[pathlib.Path]:
    home = pathlib.Path.home()
    names = ["bsk.exe", "bsk.cmd", "bsk.bat", "bsk"] if system_name() == "windows" else ["bsk"]
    return [home / ".local" / "bin" / name for name in names] + [pathlib.Path(name) for name in names]


def find_bsk() -> pathlib.Path | None:
    override = os.environ.get("BSK_BIN")
    if override and pathlib.Path(override).exists():
        return pathlib.Path(override)
    for candidate in bsk_candidates():
        if candidate.exists():
            return candidate
    found = shutil.which("bsk")
    return pathlib.Path(found) if found else None


def open_path(path: pathlib.Path) -> bool:
    try:
        if system_name() == "windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system_name() == "macos":
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def open_url(url: str) -> bool:
    try:
        if system_name() == "windows":
            os.startfile(url)  # type: ignore[attr-defined]
        elif system_name() == "macos":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class RuntimeCommand:
    command: list[str]

    def run(self, **kwargs):
        return subprocess.run(self.command, **kwargs)


def worker_command(state_path: pathlib.Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker-state", str(state_path)]
    return [sys.executable, "-m", "course_run", "worker", "--state", str(state_path)]


def _windows_process_name(pid: int) -> str:
    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def _restore_windows_browser(preferred: str, title_hint: str | None = None) -> bool:
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        if class_buffer.value != "Chrome_WidgetWin_1":
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = _windows_process_name(pid.value)
        if process_name not in {"msedge.exe", "chrome.exe"}:
            return True
        title = title_buffer.value
        score = 0
        if title_hint and title_hint.strip() and title_hint.lower() in title.lower():
            score += 10
        if preferred.lower() in title.lower():
            score += 3
        candidates.append((score, int(hwnd), title))
        return True

    try:
        user32.EnumWindows(callback_type(callback), 0)
    except Exception:
        return False
    if not candidates:
        return False
    candidates.sort(key=lambda item: item[0], reverse=True)
    hwnd = candidates[0][1]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return True


def activate_browser(preferred: str = "Microsoft Edge", title_hint: str | None = None) -> bool:
    """Best-effort activation of the browser that owns the Agent Window."""
    system = system_name()
    try:
        if system == "macos":
            script = f'tell application "{preferred}" to activate'
            try:
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, OSError):
                pass
            try:
                result = subprocess.run(["open", "-a", preferred], capture_output=True, timeout=4)
                return result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                return False

        if system == "windows":
            if _restore_windows_browser(preferred, title_hint):
                return True
            script = f"(New-Object -ComObject WScript.Shell).AppActivate('{preferred}')"
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", script],
                    capture_output=True,
                    timeout=4,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                return False

        for command in (["wmctrl", "-a", preferred], ["xdotool", "search", "--name", preferred, "windowactivate"]):
            try:
                result = subprocess.run(command, capture_output=True, timeout=3)
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
    except Exception:
        pass
    return False
