from __future__ import annotations

import json
import os
import pathlib
from dataclasses import asdict, dataclass, fields
from typing import Any

from .platform_adapter import app_data_dir, ensure_dir


@dataclass(slots=True)
class AppPaths:
    root: pathlib.Path
    config: pathlib.Path
    state: pathlib.Path
    status: pathlib.Path
    stop: pathlib.Path
    log: pathlib.Path
    stdout: pathlib.Path
    stderr: pathlib.Path


@dataclass(slots=True)
class Config:
    course_url: str = ""
    session_name: str = "课程自动播放"
    poll_seconds: int = 10
    switch_delay_seconds: int = 8
    retry_limit: int = 8
    browser: str = ""
    playback_rate: float = 1.0
    open_dashboard: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "Config":
        value = value or {}
        accepted = {field.name for field in fields(cls)}
        data = {key: value[key] for key in accepted if key in value}
        config = cls(**data)
        return config.normalized()

    def normalized(self) -> "Config":
        self.course_url = str(self.course_url or "").strip()
        self.session_name = str(self.session_name or "课程自动播放").strip() or "课程自动播放"
        self.poll_seconds = max(2, int(self.poll_seconds or 10))
        self.switch_delay_seconds = max(1, int(self.switch_delay_seconds or 8))
        self.retry_limit = max(1, int(self.retry_limit or 8))
        self.browser = str(self.browser or "").strip()
        self.playback_rate = min(4.0, max(0.25, float(self.playback_rate or 1.0)))
        self.open_dashboard = bool(self.open_dashboard)
        return self


def paths() -> AppPaths:
    root = pathlib.Path(os.environ.get("COURSE_RUN_DATA_DIR", app_data_dir()))
    return AppPaths(
        root=root,
        config=root / "config.json",
        state=root / "state.json",
        status=root / "status.json",
        stop=root / "STOP",
        log=root / "worker.log",
        stdout=root / "worker.out.log",
        stderr=root / "worker.err.log",
    )


def atomic_write_json(path: pathlib.Path, value: Any) -> None:
    ensure_dir(path.parent)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_config() -> Config:
    p = paths()
    ensure_dir(p.root)
    if not p.config.exists():
        return Config()
    try:
        return Config.from_dict(json.loads(p.config.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return Config()


def save_config(config: Config | dict[str, Any] | None = None, **updates) -> Config:
    current = load_config()
    if config is not None:
        current = config if isinstance(config, Config) else Config.from_dict(config)
    for key, value in updates.items():
        if hasattr(current, key):
            setattr(current, key, value)
    current = current.normalized()
    atomic_write_json(paths().config, asdict(current))
    return current


def load_state() -> dict[str, Any] | None:
    path = paths().state
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(paths().state, state)
    return state


def clear_state() -> None:
    try:
        paths().state.unlink()
    except FileNotFoundError:
        pass


def read_status() -> dict[str, Any]:
    path = paths().status
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "idle", "action": "idle"}


def write_status(status: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(paths().status, status)
    return status


def request_stop() -> None:
    p = paths()
    ensure_dir(p.root)
    p.stop.write_text(f"{os.getpid()}\n", encoding="utf-8")


def stop_requested() -> bool:
    return paths().stop.exists()


def remove_stop_flag() -> None:
    try:
        paths().stop.unlink()
    except FileNotFoundError:
        pass
