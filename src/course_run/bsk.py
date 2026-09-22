from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Sequence

from .platform_adapter import find_bsk, system_name

INSTALL_HINT = (
    "未找到 BrowserSkill 的 bsk CLI。\n"
    "Windows: irm https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.ps1 | iex\n"
    "macOS/Linux: curl -fsSL https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.sh | sh"
)


class BskError(RuntimeError):
    pass


@dataclass(slots=True)
class BskResult:
    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout or self.stderr


def executable() -> str:
    path = find_bsk()
    if path:
        return str(path)
    return "bsk"


def run(args: Sequence[str], timeout: int = 60, check: bool = False) -> BskResult:
    command = [executable(), *args]
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if system_name() == "windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.run(command, **kwargs)
    except FileNotFoundError as exc:
        raise BskError(INSTALL_HINT) from exc
    except subprocess.TimeoutExpired as exc:
        raise BskError(f"bsk 命令执行超时: {' '.join(command)}") from exc

    result = BskResult(process.returncode, process.stdout.strip(), process.stderr.strip())
    if check and result.code != 0:
        raise BskError(result.output or f"bsk 命令失败: {' '.join(command)}")
    return result


def run_json(args: Sequence[str], timeout: int = 60) -> Any:
    result = run(args, timeout=timeout, check=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BskError(f"bsk 返回了无效 JSON:\n{result.stdout}") from exc


def version() -> str:
    return run(["--version"], timeout=15, check=True).stdout


def doctor() -> BskResult:
    return run(["doctor"], timeout=60)


def browsers() -> list[dict[str, Any]]:
    value = run_json(["browsers", "--json"], timeout=20)
    return value if isinstance(value, list) else []


def sessions() -> list[dict[str, Any]]:
    value = run_json(["session", "list", "--json"], timeout=20)
    return value if isinstance(value, list) else []


def reload(session_id: str, tab_id: str) -> BskResult:
    return run(["reload", "--session", session_id, "--tab-id", tab_id], timeout=30)
