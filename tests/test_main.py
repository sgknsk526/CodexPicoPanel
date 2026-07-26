import os
import unittest
from unittest.mock import patch

from codex_pico_panel.__main__ import parse_args


class ParseArgsTests(unittest.TestCase):
    def test_remote_host_defaults_to_none(self):
        with patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            args = parse_args(["--port", "COM4"])

        self.assertIsNone(args.remote_host)

    def test_remote_host_uses_environment(self):
        with patch.dict(
            os.environ,
            {
                "CODEX_PICO_REMOTE_HOST": "remote-box",
            },
            clear=True,
        ):
            args = parse_args(["--port", "COM4"])

        self.assertEqual(
            args.remote_host,
            "remote-box",
        )

    def test_remote_host_argument_overrides_environment(self):
        with patch.dict(
            os.environ,
            {
                "CODEX_PICO_REMOTE_HOST": "remote-box",
            },
            clear=True,
        ):
            args = parse_args(
                [
                    "--port",
                    "COM4",
                    "--remote-host",
                    "other-box",
                ]
            )

        self.assertEqual(
            args.remote_host,
            "other-box",
        )


if __name__ == "__main__":
    unittest.main()
