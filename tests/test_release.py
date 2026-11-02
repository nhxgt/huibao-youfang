import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.launcher import bind_local_socket, open_when_ready
from release_tools.package import APP_NAME, DISTRIBUTION_NAME, create_release


class ReleaseTests(unittest.TestCase):
    def test_release_contains_program_and_public_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / APP_NAME
            root.mkdir()
            (root / (APP_NAME + ".exe")).write_bytes(b"MZ-fixture")
            archive = create_release(directory)
            self.assertEqual(archive.name, DISTRIBUTION_NAME + ".zip")
            with zipfile.ZipFile(archive) as content:
                self.assertIn(DISTRIBUTION_NAME + "/" + APP_NAME + ".exe", content.namelist())
                self.assertIn(DISTRIBUTION_NAME + "/README.txt", content.namelist())
                self.assertIsNone(content.testzip())

    def test_release_refuses_personal_data_and_keeps_existing_archive(self):
        for item in ["reports.sqlite3", ".env", "data/reports.sqlite3", "files/private-file"]:
            with self.subTest(item=item), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / APP_NAME
                root.mkdir()
                (root / (APP_NAME + ".exe")).write_bytes(b"MZ-fixture")
                archive = create_release(directory)
                previous = archive.read_bytes()
                forbidden = root / item
                forbidden.parent.mkdir(parents=True, exist_ok=True)
                forbidden.write_text("must not distribute")
                with self.assertRaises(ValueError):
                    create_release(directory)
                self.assertEqual(archive.read_bytes(), previous)

    def test_busy_port_falls_back_without_releasing_the_reserved_port(self):
        with bind_local_socket(0) as occupied:
            occupied.listen()
            port = occupied.getsockname()[1]
            with self.assertRaises(OSError):
                bind_local_socket(port, allow_fallback=False)
            with bind_local_socket(port) as alternative:
                self.assertEqual(alternative.getsockname()[0], "127.0.0.1")
                self.assertNotEqual(alternative.getsockname()[1], port)

    def test_browser_opens_only_after_server_is_ready(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        opener = MagicMock()
        opener.open.side_effect = [OSError("starting"), response]
        with patch("backend.launcher.urllib.request.build_opener", return_value=opener), \
                patch("backend.launcher.time.sleep"), patch("backend.launcher.webbrowser.open") as opened:
            open_when_ready("http://127.0.0.1:12345")
        self.assertEqual(opener.open.call_count, 2)
        opened.assert_called_once_with("http://127.0.0.1:12345")
