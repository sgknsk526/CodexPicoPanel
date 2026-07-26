"""Current in-memory state of the resident process."""

import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone


@dataclass(frozen=True)
class RuntimeSnapshot:
    pico_connected: bool = False
    pico_port: str | None = None
    key_mask: int = 0
    last_error: str | None = None
    connect_count: int = 0
    disconnect_count: int = 0
    last_disconnect_at: str | None = None
    last_disconnect_reason: str | None = None


class RuntimeState:
    """Share a small consistent snapshot with the local status server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = RuntimeSnapshot()

    def update(self, **changes: object) -> None:
        with self._lock:
            self._value = replace(self._value, **changes)

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return self._value

    def as_dict(self) -> dict[str, object]:
        return asdict(self.snapshot())

    def record_connection(
        self,
        port: str,
    ) -> None:
        with self._lock:
            self._value = replace(
                self._value,
                pico_connected=True,
                pico_port=port,
                last_error=None,
                connect_count=(
                    self._value.connect_count + 1
                ),
            )

    def record_disconnect(
        self,
        reason: str | None,
    ) -> None:
        with self._lock:
            self._value = replace(
                self._value,
                pico_connected=False,
                pico_port=None,
                disconnect_count=(
                    self._value.disconnect_count + 1
                ),
                last_disconnect_at=datetime.now(
                    timezone.utc
                ).isoformat(),
                last_disconnect_reason=reason,
            )
