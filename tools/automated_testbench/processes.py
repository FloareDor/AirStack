#!/usr/bin/env python3
"""Subprocess helpers with per-command logs and bounded cleanup."""

from __future__ import annotations

import shlex
import subprocess
import threading
from pathlib import Path
from typing import Callable, Sequence


class CommandError(RuntimeError):
    def __init__(
        self, message: str, command: Sequence[str], returncode: int | None = None
    ):
        super().__init__(message)
        self.command = list(command)
        self.returncode = returncode


class ManagedProcess:
    def __init__(
        self,
        command: Sequence[str],
        log_path: Path,
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.command = list(command)
        self.log_path = log_path
        self._log = log_path.open("a", encoding="utf-8")
        self._log.write(f"$ {shlex.join(self.command)}\n")
        self._log.flush()
        self.process = subprocess.Popen(
            self.command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._on_line = on_line
        self._thread = threading.Thread(target=self._copy_output, daemon=True)
        self._thread.start()

    def _copy_output(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._log.write(line)
            self._log.flush()
            if self._on_line is not None:
                self._on_line(line.rstrip("\r\n"))

    def poll(self) -> int | None:
        return self.process.poll()

    def stop(self, timeout_s: float = 10.0) -> int:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self._thread.join(timeout=2)
        self._log.close()
        return int(self.process.returncode or 0)


def run_logged(
    command: Sequence[str],
    log_path: Path,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float = 60.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"$ {shlex.join(command)}\n")
        log.flush()
        try:
            result = subprocess.run(
                list(command),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            log.write(output)
            raise CommandError(
                f"command timed out after {timeout_s:.1f}s", command
            ) from exc
        log.write(result.stdout)
        log.flush()
    if check and result.returncode != 0:
        raise CommandError(
            f"command failed with exit code {result.returncode}",
            command,
            result.returncode,
        )
    return result
