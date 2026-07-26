import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from codex_pico_panel.panel_state import PanelState
from codex_pico_panel.runtime import RuntimeState
from codex_pico_panel.status_server import StatusServer
from codex_pico_panel.task_slots import TaskSlots
from codex_pico_panel.task_status import TaskStatuses


class StatusServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.events = queue.Queue()
        self.slots = TaskSlots(
            Path(self.temporary_directory.name)
            / "slots.json"
        )
        self.statuses = TaskStatuses()

    def start_server(
        self,
        runtime,
        panel,
        shutdown_callback=None,
    ):
        server = StatusServer(
            runtime,
            panel,
            self.events,
            self.slots,
            self.statuses,
            port=0,
            shutdown_callback=shutdown_callback,
        )
        server.start()
        self.addCleanup(server.stop)
        return server

    def test_status_api_contains_panel_and_codex_state(self):
        runtime = RuntimeState()
        runtime.update(
            pico_connected=True,
            pico_port="COM4",
            key_mask=0x8001,
        )
        panel = PanelState()
        panel.set(0, 1)
        panel.set(15, 7)
        self.slots.register(7, "thread-7")
        self.statuses.set_active("thread-7")
        self.statuses.set_reasoning_effort(
            "thread-7",
            "high",
        )

        server = self.start_server(runtime, panel)
        host, port = server.address

        with urlopen(
            f"http://{host}:{port}/",
            timeout=2,
        ) as response:
            html = response.read().decode("utf-8")
        with urlopen(
            f"http://{host}:{port}/api/status",
            timeout=2,
        ) as response:
            status = json.load(response)

        self.assertIn(
            "<title>Codex Pico Panel</title>",
            html,
        )
        self.assertIn('id="panel"', html)
        self.assertEqual(status["pico_port"], "COM4")
        self.assertEqual(
            status["key_mask_hex"],
            "0x8001",
        )
        self.assertEqual(
            status["pressed_keys"],
            ["0", "F"],
        )
        self.assertEqual(status["led_states"][0], 1)
        self.assertEqual(status["led_states"][15], 7)
        self.assertEqual(
            status["codex_context"][
                "reasoning_effort"
            ],
            "high",
        )
        self.assertEqual(
            status["task_slots"]["7"],
            "thread-7",
        )

    def test_non_object_hook_payload_returns_400(self):
        runtime = RuntimeState()
        panel = PanelState()
        server = self.start_server(runtime, panel)
        host, port = server.address
        request = Request(
            f"http://{host}:{port}/api/hooks",
            data=b"[]",
            method="POST",
            headers={
                "Content-Type": "application/json",
            },
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)

        self.assertEqual(context.exception.code, 400)

    def test_shutdown_api_invokes_callback(self):
        runtime = RuntimeState()
        panel = PanelState()
        requested = threading.Event()
        server = self.start_server(
            runtime,
            panel,
            shutdown_callback=requested.set,
        )
        host, port = server.address
        request = Request(
            f"http://{host}:{port}/api/shutdown",
            data=b"",
            method="POST",
        )

        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 202)

        self.assertTrue(requested.wait(timeout=2))


if __name__ == "__main__":
    unittest.main()
