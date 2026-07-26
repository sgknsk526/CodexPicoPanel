import sys
import unittest

from codex_pico_panel.codex.app_server import (
    AppServerClient,
)


class AppServerClientTests(unittest.TestCase):
    def test_initialize_has_a_bounded_timeout(self):
        command = [
            sys.executable,
            "-u",
            "-c",
            "import time; time.sleep(10)",
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "timed out",
        ):
            AppServerClient(
                command,
                request_timeout=0.1,
            )


if __name__ == "__main__":
    unittest.main()
