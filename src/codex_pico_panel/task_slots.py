"""Persistent Pico slot registrations."""

from __future__ import annotations

import json
import os
from pathlib import Path


class TaskSlots:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._bindings: dict[int, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return

        try:
            document = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(document, dict):
            return

        slots = document.get("slots")

        if not isinstance(slots, dict):
            return

        for raw_slot, value in slots.items():
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                continue

            if not 1 <= slot <= 7:
                continue

            if not isinstance(value, dict):
                continue

            conversation_id = value.get(
                "conversation_id"
            )

            if (
                isinstance(conversation_id, str)
                and conversation_id
            ):
                self._bindings[slot] = conversation_id

    def _save(
        self,
        bindings: dict[int, str],
    ) -> None:
        document = {
            "version": 1,
            "slots": {
                str(slot): {
                    "conversation_id": conversation_id,
                }
                for slot, conversation_id
                in sorted(bindings.items())
            },
        }

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.path.with_name(
            self.path.name + ".tmp"
        )

        try:
            temporary_path.write_text(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def is_registered(self, slot: int) -> bool:
        return slot in self._bindings

    def get(self, slot: int) -> str | None:
        return self._bindings.get(slot)

    def register(
        self,
        slot: int,
        conversation_id: str,
    ) -> None:
        if not 1 <= slot <= 7:
            raise ValueError("slot must be 1..7")

        if not conversation_id:
            raise ValueError(
                "conversation_id must not be empty"
            )

        bindings = dict(self._bindings)
        bindings[slot] = conversation_id
        self._save(bindings)
        self._bindings = bindings

    def unregister(self, slot: int) -> None:
        if slot not in self._bindings:
            return

        bindings = dict(self._bindings)
        del bindings[slot]
        self._save(bindings)
        self._bindings = bindings

    def snapshot(self) -> dict[int, str]:
        return dict(self._bindings)

    def find_slot_by_conversation_id(
        self,
        conversation_id: str,
    ) -> int | None:
        for slot, registered_id in self._bindings.items():
            if registered_id == conversation_id:
                return slot

        return None
