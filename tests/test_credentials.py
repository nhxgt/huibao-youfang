import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.credentials import CredentialError, protect_key, unprotect_key
from backend.migrate_data import migrate_data
from backend.models import ModelSettings
from backend.paths import APP_NAME, resolve_data_dir
from backend.store import Store, timestamp


@unittest.skipUnless(sys.platform == "win32", "Requires Windows current-user DPAPI")
class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = TestClient(self.app, base_url="http://localhost", headers={"X-Work-Report": "1"})
        self.client.__enter__()
        self.config = {"name": "test-model", "base_url": "https://model.example/v1", "api_key": "restart-fixture-key"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def save(self, **changes):
        config = {**self.config, **changes}
        response = self.client.put("/api/model-settings", json=config)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_real_dpapi_roundtrip_and_endpoint_binding(self):
        record = protect_key("fixture-secret", "https://one.example/v1")
        self.assertNotIn("fixture-secret", json.dumps(record))
        self.assertEqual(unprotect_key(record, "https://one.example/v1"), "fixture-secret")
        with self.assertRaises(CredentialError):
            unprotect_key(record, "https://two.example/v1")
        record["ciphertext"] = base64.b64encode(b"invalid protected data").decode()
        with self.assertRaises(CredentialError):
            unprotect_key(record, "https://one.example/v1")

    def test_new_process_restores_key_without_plaintext_storage(self):
        self.assertTrue(self.save()["key_persisted"])
        code = "from pathlib import Path; import sys; from backend.app import create_app; s=create_app(Path(sys.argv[1])).state.service; assert s.api_key=='restart-fixture-key'; print('restored')"
        result = subprocess.run([sys.executable, "-c", code, str(self.root)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "restored")
        for file in self.root.glob("reports.sqlite3*"):
            self.assertNotIn(b"restart-fixture-key", file.read_bytes())
        for endpoint in ["/api/model-settings", "/api/bootstrap"]:
            text = self.client.get(endpoint).text
            self.assertNotIn("restart-fixture-key", text)
            self.assertNotIn("ciphertext", text)

    def test_replace_and_leave_empty_preserves_saved_key(self):
        self.save()
        self.save(api_key="replacement-fixture-key")
        self.save(api_key="")
        restarted = create_app(self.root)
        self.assertEqual(restarted.state.service.api_key, "replacement-fixture-key")

    def test_invalid_key_input_is_rejected_without_overwriting_saved_credentials(self):
        self.save()
        invalid = ["误填的密钥内容", "sk-fixture\u200b", "sk-fixture\nother", "sk-fixture other",
                   "sk-fixture\tother", "sk-fixture\x7f", "\u2022" * 40, "*" * 40]
        before = self.app.state.store.get_setting("model_credentials")
        for key in invalid:
            with self.subTest(case=invalid.index(key)):
                result = self.client.put("/api/model-settings", json={**self.config, "api_key": key})
                self.assertEqual(result.status_code, 422)
                self.assertNotIn(key, result.text)
                self.assertEqual(self.app.state.store.get_setting("model_credentials"), before)
        self.assertEqual(create_app(self.root).state.service.api_key, "restart-fixture-key")

    def test_invalid_saved_key_is_flagged_without_deleting_it_and_can_be_replaced(self):
        self.save()
        record = protect_key("误填的密钥内容", self.config["base_url"])
        self.app.state.store.set_setting("model_credentials", record)
        restarted = create_app(self.root, httpx.MockTransport(lambda r: self.fail("must not contact provider")))
        with TestClient(restarted, base_url="http://localhost", headers={"X-Work-Report": "1"}) as client:
            settings = client.get("/api/model-settings").json()
            self.assertTrue(settings["credential_error"])
            self.assertFalse(settings["configured"])
            self.assertFalse(settings["has_api_key"])
            self.assertEqual(restarted.state.store.get_setting("model_credentials"), record)
            result = client.post("/api/model-settings/test")
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json()["error"]["code"], "invalid_saved_api_key")
            self.assertNotIn("误填的密钥内容", result.text)
            self.assertEqual(client.put("/api/model-settings", json=self.config).status_code, 200)
        self.assertTrue(create_app(self.root).state.service.settings()["configured"])

    def test_invalid_environment_key_is_flagged_on_startup(self):
        with patch.dict(os.environ, {"WORK_REPORT_API_KEY": "误填的密钥内容"}):
            restarted = create_app(self.root / "invalid-env")
        self.assertTrue(restarted.state.service.settings()["credential_error"])
        self.assertFalse(restarted.state.service.settings()["configured"])

    def test_clear_does_not_restore_old_environment_key(self):
        self.save()
        self.assertEqual(self.client.delete("/api/model-settings/key").status_code, 200)
        with patch.dict(os.environ, {"WORK_REPORT_API_KEY": "environment-fixture"}):
            restarted = create_app(self.root)
        self.assertFalse(restarted.state.service.settings()["has_api_key"])
        self.assertEqual(restarted.state.service.settings()["name"], "test-model")
        self.save(api_key="new-after-clear")
        self.assertEqual(create_app(self.root).state.service.api_key, "new-after-clear")

    def test_environment_key_is_available_until_user_saves_or_clears(self):
        with patch.dict(os.environ, {"WORK_REPORT_API_KEY": "environment-fixture"}):
            other = create_app(self.root / "env-user")
        self.assertEqual(other.state.service.api_key, "environment-fixture")
        self.assertFalse(other.state.service.settings()["key_persisted"])

    def test_corrupted_or_mismatched_credentials_do_not_break_startup(self):
        self.save()
        self.app.state.store.set_setting("model", {"name": "test-model", "base_url": "https://other.example/v1"})
        restarted = create_app(self.root)
        self.assertFalse(restarted.state.service.settings()["configured"])
        self.assertTrue(restarted.state.service.settings()["credential_error"])
        self.app.state.store.set_setting("model_credentials", {"scheme": "unknown", "ciphertext": "private-malformed"})
        restarted = create_app(self.root)
        self.assertTrue(restarted.state.service.settings()["credential_error"])
        self.assertFalse(restarted.state.service.settings()["has_api_key"])

    def test_encryption_failure_keeps_previous_configuration(self):
        self.save()
        before = self.app.state.store.get_setting("model")
        with patch("backend.service.protect_key", side_effect=CredentialError("test failure")):
            result = self.client.put("/api/model-settings", json={**self.config, "base_url": "https://other.example/v1"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("restart-fixture-key", result.text)
        self.assertEqual(self.app.state.store.get_setting("model"), before)
        self.assertEqual(create_app(self.root).state.service.api_key, "restart-fixture-key")

    def test_database_failure_rolls_back_model_and_credential_together(self):
        self.save()
        before = self.app.state.store.get_setting("model_credentials")
        with self.app.state.store.connect() as con:
            con.execute("CREATE TRIGGER reject_credential BEFORE INSERT ON settings WHEN NEW.key='model_credentials' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.state.service.save_model_settings(ModelSettings(
                name="changed", base_url="https://other.example/v1", api_key="new-fixture"))
        self.assertEqual(self.app.state.store.get_setting("model")["base_url"], "https://model.example/v1")
        self.assertEqual(self.app.state.store.get_setting("model_credentials"), before)
        self.assertEqual(self.app.state.service.api_key, "restart-fixture-key")

    def test_separate_user_data_roots_do_not_share_configuration(self):
        self.save()
        with patch.dict(os.environ, {"WORK_REPORT_API_KEY": ""}):
            other = create_app(self.root / "other-user")
        self.assertFalse(other.state.service.settings()["has_api_key"])
        self.assertEqual(other.state.service.settings()["name"], "")


class DataLocationTests(unittest.TestCase):
    def test_windows_per_user_directory_and_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch("backend.paths.sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": str(base), "WORK_REPORT_DATA_DIR": ""}):
                self.assertEqual(resolve_data_dir(), (base / APP_NAME).resolve())
                with patch.dict(os.environ, {"WORK_REPORT_DATA_DIR": str(base / "isolated")}):
                    self.assertEqual(resolve_data_dir(), (base / "isolated").resolve())
                    self.assertEqual(resolve_data_dir(base / "explicit"), (base / "explicit").resolve())

    def make_source(self, root):
        store = Store(root)
        store.set_setting("profile", {"name": "迁移测试", "role": "产品经理", "dept": ""})
        file_id, content = "a" * 32, b"migration fixture"
        (store.files_dir / file_id).write_bytes(content)
        store.add_file({"id": file_id, "name": "fixture.txt", "date": "2026-10-21", "size": len(content),
                        "media_type": "text/plain", "sha256": hashlib.sha256(content).hexdigest(), "created_at": timestamp()})
        store.save_report("daily", "2026-10-21", "2026-10-21", "2026-10-21", {"points": [{"title": "迁移测试"}]}, [file_id], 0)
        return store

    def test_migration_copies_database_and_files_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "old", Path(directory) / "user"
            self.make_source(source)
            self.assertEqual(migrate_data(source, target), {"reports": 1, "files": 1})
            copied = Store(target)
            self.assertEqual(copied.report("daily", "2026-10-21")["files"][0]["name"], "fixture.txt")
            self.assertEqual((target / "files" / ("a" * 32)).read_bytes(), (source / "files" / ("a" * 32)).read_bytes())
            with self.assertRaises(ValueError):
                migrate_data(source, target)

    def test_migration_accepts_only_empty_initialized_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "old", Path(directory) / "user"
            self.make_source(source)
            Store(target)
            self.assertEqual(migrate_data(source, target)["files"], 1)

    def test_migration_missing_file_does_not_install_incomplete_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "old", Path(directory) / "user"
            self.make_source(source)
            (source / "files" / ("a" * 32)).unlink()
            with self.assertRaises(FileNotFoundError):
                migrate_data(source, target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).glob("report-migration-*")), [])

    def test_migration_refuses_non_app_content_in_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "old", Path(directory) / "user"
            self.make_source(source)
            target.mkdir()
            (target / "files").write_text("keep this unrelated file")
            with self.assertRaises(ValueError):
                migrate_data(source, target)
            self.assertEqual((target / "files").read_text(), "keep this unrelated file")
