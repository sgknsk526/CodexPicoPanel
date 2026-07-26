"""Keep the reverse SSH hook tunnel connected."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading


LOGGER = logging.getLogger(__name__)

RECONNECT_SECONDS = 3.0


class SshHookTunnel(threading.Thread):
    def __init__(
        self,
        host: str,
        remote_port: int = 48974,
        local_port: int = 48973,
    ) -> None:
        super().__init__(
            name="ssh-hook-tunnel",
            daemon=True,
        )

        self.host = host
        self.remote_port = remote_port
        self.local_port = local_port

        self._stop_event = threading.Event()
        self._process: subprocess.Popen | None = None

    def stop(self) -> None:
        self._stop_event.set()

        process = self._process

        if process is not None:
            process.terminate()

    def _command(self) -> list[str]:
        ssh = shutil.which("ssh")

        if ssh is None:
            raise RuntimeError(
                "Windows OpenSSH ssh.exe was not found"
            )

        forwarding = (
            f"127.0.0.1:{self.remote_port}:"
            f"127.0.0.1:{self.local_port}"
        )

        return [
            ssh,
            "-N",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-R",
            forwarding,
            self.host,
        ]

    def _run_once(self) -> None:
        command = self._command()

        LOGGER.info(
            "Starting SSH hook tunnel to %s",
            self.host,
        )

        creation_flags = getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        )

        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        try:
            while not self._stop_event.is_set():
                return_code = self._process.poll()

                if return_code is not None:
                    LOGGER.warning(
                        "SSH hook tunnel exited with code %d",
                        return_code,
                    )
                    return

                self._stop_event.wait(0.5)
        finally:
            process = self._process
            self._process = None

            if process is not None:
                if process.poll() is None:
                    process.terminate()

                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_once()
            except Exception:
                LOGGER.exception(
                    "SSH hook tunnel failed"
                )

            self._stop_event.wait(
                RECONNECT_SECONDS
            )
