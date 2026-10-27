"""Sandboxed command runner.

Docker (no network, memory/CPU limits) when the daemon and image are
available; otherwise a local subprocess with timeout. Oracle/test files
listed in readonly_paths are hash-verified before AND after in both modes.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(paths: list[str | Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            out[str(pp.resolve())] = sha256_file(pp)
    return out


def verify_snapshot(snap: dict[str, str]) -> list[str]:
    """Return list of changed/missing files (empty = untouched)."""
    changed: list[str] = []
    for name, digest in snap.items():
        pp = Path(name)
        if not pp.is_file() or sha256_file(pp) != digest:
            changed.append(name)
    return changed


def docker_daemon_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        p = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=15, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return p.returncode == 0


def docker_image_present(image: str) -> bool:
    try:
        p = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return p.returncode == 0


@dataclass
class RunResult:
    engine: str  # "docker" | "local"
    returncode: int
    stdout: str
    stderr: str
    readonly_ok: bool
    readonly_changed: list[str]
    timed_out: bool = False


def run_command(
    cmd: list[str],
    *,
    cwd: str | Path,
    timeout_s: float = 10,
    memory_mb: int = 512,
    readonly_paths: list[str | Path] | None = None,
    use_docker: bool | None = None,
    image: str = "migrate-sandbox:latest",
) -> RunResult:
    """Run cmd sandboxed. Docker preferred; local fallback is explicit."""
    before = snapshot(list(readonly_paths or []))
    want_docker = docker_daemon_ok() if use_docker is None else use_docker
    engine = "local"
    timed_out = False
    if want_docker and docker_daemon_ok() and docker_image_present(image):
        engine = "docker"
        full = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            f"{memory_mb}m",
            "--cpus",
            "1.0",
            "-v",
            f"{Path(cwd).resolve()}:/work",
            "-w",
            "/work",
            image,
            *cmd,
        ]
    else:
        full = cmd
    try:
        p = subprocess.run(
            full, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s, check=False
        )
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, str(e.stdout or ""), f"timeout after {timeout_s}s"
        timed_out = True
    changed = verify_snapshot(before)
    return RunResult(
        engine=engine,
        returncode=rc,
        stdout=out,
        stderr=err,
        readonly_ok=not changed,
        readonly_changed=changed,
        timed_out=timed_out,
    )
