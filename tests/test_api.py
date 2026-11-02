import io
import json
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.extraction import extract
from backend.service import week_label, week_range


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
        self.app = create_app(Path(self.temp.name), httpx.MockTransport(self.model_response))
        self.client = TestClient(self.app, base_url="http://localhost", headers={"X-Work-Report": "1"})
        self.client.__enter__()
        self.client.put("/api/profile", json={"name": "林晓", "role": "产品经理", "dept": ""})
        result = self.client.put("/api/model-settings", json={
            "name": "test-model", "base_url": "https://model.example/v1", "api_key": "test-only-key"})
        self.assertEqual(result.status_code, 200)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def model_response(self, request):
        self.assertEqual(str(request.url), "https://model.example/v1/chat/completions")
        self.assertEqual(request.headers["authorization"], "Bearer test-only-key")
        body = json.loads(request.content)
        self.calls.append(body)
        self.assertEqual(body["messages"][0]["role"], "system")
        content = body["messages"][1]["content"]
        payload = json.loads(content if isinstance(content, str) else content[0]["text"])
        if "file_id" in payload:
            answer = {"status": "ok", "file_id": payload["file_id"], "file_name": payload["file_name"],
                      "document_stage": "未说明", "summary": "需求评审记录",
                      "facts": [{"id": "f1", "content": "完成需求评审", "category": "成果",
                                 "work_status": "已完成", "responsibility": "用户", "locator": "正文，第1行",
                                 "certainty": "明确"}], "warnings": []}
        elif "daily_reports" in payload:
            answer = {"status": "ok", "items": [{
                "title": "推进需求评审", "text": "本周完成需求评审。",
                "source_refs": [f"daily:{payload['daily_reports'][0]['id']}#1"]}], "warnings": []}
        else:
            refs = ["input:work_content"] if payload["work_content"] else [
                f"file:{payload['file_analyses'][0]['file_id']}#f1"]
            answer = {"status": "ok", "items": [{"title": "完成需求评审", "text": "已整理评审记录。",
                                               "source_refs": refs}], "warnings": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)},
                                                     "finish_reason": "stop"}]})

    def upload(self, when="2026-10-19", name="评审记录.txt", content="完成需求评审"):
        raw = content.encode() if isinstance(content, str) else content
        response = self.client.post("/api/files", params={"report_date": when, "filename": name},
                                    content=raw, headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def save(self, when, files=None, revision=0):
        response = self.client.put(f"/api/reports/daily/{when}", json={
            "points": [{"title": "完成需求评审", "text": "整理评审记录", "source_refs": ["input:work_content"]}],
            "notes": "完成需求评审", "file_ids": files or [], "expected_revision": revision})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_real_file_generation_save_and_zip_round_trip(self):
        file = self.upload()
        response = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "file_ids": [file["id"]]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(response.json()["items"][0]["source_refs"], [f"file:{file['id']}#f1"])
        self.save("2026-10-19", [file["id"]])
        self.assertEqual(self.client.get("/api/reports").json()["total"], 1)
        archive = self.client.post("/api/archives", json={
            "kind": "daily", "report_date": "2026-10-19", "file_ids": [file["id"]]})
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            self.assertEqual(z.namelist(), ["01_评审记录_20261019.txt"])
            self.assertEqual(z.read(z.namelist()[0]).decode(), "完成需求评审")
            self.assertIsNone(z.testzip())
        self.assertEqual(list(self.app.state.store.temp_dir.iterdir()), [])

    def test_week_uses_saved_sources_chronological_files_and_cross_month_label(self):
        second = self.upload("2026-11-01", "同名.txt", "周日成果")
        first = self.upload("2026-10-26", "同名.txt", "周一成果")
        self.save("2026-11-01", [second["id"]])
        self.save("2026-10-26", [first["id"]])
        sources = self.client.get("/api/weeks/2026-11-01/sources").json()
        self.assertEqual(sources["week_label"], "11月第1周")
        self.assertEqual(sources["period_start"], "2026-10-26")
        self.assertEqual(self.client.get("/api/weeks/2026-10-26/sources").json(), sources)
        self.assertEqual([f["id"] for f in sources["files"]], [first["id"], second["id"]])
        generated = self.client.post("/api/reports/weekly/generate", json={
            "anchor_date": "2026-10-26", "requirements": "按项目归类"})
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(generated.json()["status"], "partial")
        payload = json.loads(self.calls[-1]["messages"][1]["content"])
        self.assertEqual(payload["requirements"], "按项目归类")
        self.assertEqual(payload["week_label"], "11月第1周")
        archive = self.client.post("/api/archives", json={"kind": "weekly", "report_date": "2026-10-26"})
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            self.assertEqual(z.namelist(), ["01_同名_20261026.txt", "02_同名_20261101.txt"])
        self.assertIn("filename*", archive.headers["content-disposition"])
        from urllib.parse import unquote
        self.assertIn("11月第1周_", unquote(archive.headers["content-disposition"]))

    def test_credentials_are_never_returned_or_written_to_database(self):
        self.assertNotIn("test-only-key", self.client.get("/api/bootstrap").text)
        settings = self.client.get("/api/model-settings").json()
        self.assertTrue(settings["has_api_key"])
        self.assertNotIn("api_key", self.app.state.store.get_setting("model"))
        second = create_app(Path(self.temp.name))
        self.assertTrue(second.state.service.settings()["has_api_key"])
        self.assertEqual(second.state.service.model_client().connection.api_key, "test-only-key")
        self.assertEqual(second.state.service.profile()["name"], "林晓")
        bad = self.client.put("/api/model-settings", json={
            "name": "x", "base_url": "https://model.example/v1", "api_key": "private-invalid-key\n"})
        # Whitespace surrounding keys is stripped, embedded line breaks are rejected.
        bad = self.client.put("/api/model-settings", json={
            "name": "x", "base_url": "https://model.example/v1", "api_key": "private\ninvalid"})
        self.assertEqual(bad.status_code, 422)
        self.assertNotIn("private", bad.text)
        changed = self.client.put("/api/model-settings", json={
            "name": "x", "base_url": "https://another.example/v1"})
        self.assertEqual(changed.status_code, 422)

    def test_clear_saved_key_survives_restart(self):
        response = self.client.delete("/api/model-settings/key")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_api_key"])
        restarted = create_app(Path(self.temp.name))
        self.assertFalse(restarted.state.service.settings()["has_api_key"])
        self.assertEqual(restarted.state.service.settings()["name"], "test-model")

    def test_revision_conflict_and_persistence(self):
        file = self.upload()
        self.save("2026-10-19", [file["id"]])
        conflict = self.client.put("/api/reports/daily/2026-10-19", json={
            "points": [{"title": "覆盖"}], "file_ids": [], "expected_revision": 0})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get("/api/reports/daily/2026-10-19").json()["points"][0]["title"], "完成需求评审")
        restarted = create_app(Path(self.temp.name))
        self.assertEqual(restarted.state.store.report("daily", "2026-10-19")["files"][0]["id"], file["id"])

    def test_history_date_filter_includes_daily_and_covering_week(self):
        self.save("2026-10-20")
        self.save("2026-10-26")
        response = self.client.put("/api/reports/weekly/2026-10-22", json={"points": [{"title": "本周总结"}]})
        self.assertEqual(response.status_code, 200)
        result = self.client.get("/api/reports?on_date=2026-10-20&limit=1").json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)
        second = self.client.get("/api/reports?on_date=2026-10-20&limit=1&offset=1").json()
        self.assertNotEqual(result["items"][0]["id"], second["items"][0]["id"])
        result = self.client.get("/api/reports?on_date=2026-10-25").json()
        self.assertEqual([r["kind"] for r in result["items"]], ["weekly"])
        self.assertEqual(self.client.get("/api/reports?on_date=2026-10-18").json()["total"], 0)
        self.assertEqual(self.client.get("/api/reports?on_date=2026-10-20&kind=daily").json()["total"], 1)
        self.assertEqual(self.client.get("/api/reports").json()["total"], 3)
        self.assertEqual(self.client.get("/api/reports?on_date=invalid").status_code, 422)

    def test_validation_empty_input_wrong_date_and_path_traversal(self):
        empty = self.client.post("/api/reports/daily/generate", json={"report_date": "2026-10-19"})
        self.assertEqual(empty.status_code, 422)
        invalid = self.client.post("/api/files", params={"report_date": "2026-10-19", "filename": "../escape.txt"}, content=b"x")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.client.get("/api/files/../../data/reports.sqlite3/download").status_code, 404)
        file = self.upload()
        wrong = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-20", "file_ids": [file["id"]]})
        self.assertEqual(wrong.status_code, 422)
        oversized = self.client.post("/api/files", params={"report_date": "2026-10-19", "filename": "large.txt"},
                                     content=b"x", headers={"Content-Length": str(51 * 1024 * 1024)})
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.client.post("/api/archives", json={"kind": "daily", "report_date": "2026-10-19"}).status_code, 422)

    def test_no_fake_success_when_missing_model_or_sources(self):
        self.app.state.service.api_key = ""
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审"})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "model_not_configured")
        self.assertEqual(self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"}).status_code, 422)

    def test_unreadable_files_return_insufficient_evidence(self):
        file = self.upload(name="成果.bin", content=b"\x00\x01")
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "file_ids": [file["id"]]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "insufficient_information")
        self.assertEqual(result.json()["items"], [])
        self.assertEqual(len(self.calls), 0)

    def test_model_errors_redacted_and_invalid_citations_rejected(self):
        self.app.state.service.transport = httpx.MockTransport(
            lambda r: httpx.Response(401, json={"error": "test-only-key"}))
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审"})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("test-only-key", result.text)
        self.app.state.service.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"status": "ok", "items": [
                {"title": "虚构成果", "source_refs": ["invented"]}], "warnings": []})}}]}))
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审"})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.json()["error"]["code"], "invalid_evidence_references")

    def test_local_origin_protection(self):
        response = self.client.put("/api/profile", json={"name": "x", "role": "x"},
                                   headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 403)
        response = self.client.put("/api/profile", json={"name": "x", "role": "x"},
                                   headers={"X-Work-Report": ""})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "attacker.example"}).status_code, 400)

    def test_drafts_and_text_only_generation(self):
        result = self.client.put("/api/drafts/daily/2026-10-19", json={
            "report_date": "2026-10-19", "notes": "完成需求评审"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get("/api/drafts/daily/2026-10-19").json()["draft"]["notes"], "完成需求评审")
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成需求评审"})
        self.assertEqual(result.status_code, 200)
        self.save("2026-10-19")
        self.assertIsNone(self.client.get("/api/drafts/daily/2026-10-19").json()["draft"])

    def test_weekly_generation_rejects_save_after_source_revision_changes(self):
        self.save("2026-10-19")
        result = self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"}).json()
        self.save("2026-10-19", revision=1)
        response = self.client.put("/api/reports/weekly/2026-10-20", json={
            "points": result["items"], "source_revisions": result["source_revisions"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "weekly_sources_changed")

    def test_weekly_draft_is_shared_across_the_same_natural_week(self):
        self.client.put("/api/drafts/weekly/2026-10-20", json={
            "report_date": "2026-10-20", "notes": "按项目归类"})
        self.assertEqual(self.client.get("/api/drafts/weekly/2026-10-22").json()["draft"]["notes"], "按项目归类")
        self.save("2026-10-19")
        self.client.put("/api/reports/weekly/2026-10-22", json={"points": [{"title": "完成评审"}]})
        self.assertIsNone(self.client.get("/api/drafts/weekly/2026-10-20").json()["draft"])

    def test_invalid_auth_header_is_not_misreported_as_model_output(self):
        self.app.state.service.api_key = "误填的密钥内容"
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审"})
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(result.json()["error"]["code"], "invalid_api_key")
        self.assertNotIn("误填的密钥内容", result.text)
        self.assertEqual(self.calls, [])

    def test_model_timeout_and_invalid_json_are_actionable(self):
        def timeout(request):
            raise httpx.ReadTimeout("private upstream details")
        self.app.state.service.transport = httpx.MockTransport(timeout)
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审"})
        self.assertEqual(result.status_code, 504)
        self.assertNotIn("private", result.text)
        self.app.state.service.transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "non-json"}}]}))
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审"})
        self.assertEqual(result.json()["error"]["code"], "invalid_model_response")

    def test_malformed_provider_structure_returns_actionable_error(self):
        for content in [{"choices": [None]}, {"choices": ["invalid"]},
                        {"choices": [{"message": {"content": [None]}}]}]:
            with self.subTest(content=content):
                self.app.state.service.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=content))
                result = self.client.post("/api/reports/daily/generate", json={
                    "report_date": "2026-10-19", "work_content": "完成评审"})
                self.assertEqual(result.status_code, 502)
                self.assertEqual(result.json()["error"]["code"], "invalid_model_response")

    def test_weekly_generation_accepts_combined_daily_attachments_over_thirty(self):
        first = [self.upload("2026-10-19", f"成果{i}.bin", b"data")["id"] for i in range(20)]
        second = [self.upload("2026-10-20", f"成果{i}.bin", b"data")["id"] for i in range(11)]
        self.save("2026-10-19", first)
        self.save("2026-10-20", second)
        result = self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["items"])
        result = self.client.put("/api/reports/weekly/2026-10-20", json={
            "points": result.json()["items"], "warnings": result.json()["warnings"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()["files"]), 31)

    def test_history_page_reads_only_requested_rows_in_bounded_queries(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        self.save("2026-10-19", [self.upload()["id"]])
        self.save("2026-10-20")
        statements = []
        connect = self.app.state.store.connect

        @contextmanager
        def traced_connect():
            with connect() as con:
                con.set_trace_callback(statements.append)
                yield con

        with patch.object(self.app.state.store, "connect", traced_connect):
            result = self.client.get("/api/reports?limit=1&offset=1").json()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["date"], "2026-10-19")
        self.assertEqual(len(result["items"][0]["files"]), 1)
        queries = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        self.assertLessEqual(len(queries), 3, queries)
        self.assertTrue(any("LIMIT" in sql.upper() for sql in queries))

    def test_many_generation_warnings_remain_saveable(self):
        file = self.upload(name="unreadable.bin", content=b"fixture")
        answer = {"status": "partial", "items": [{"title": "完成评审", "source_refs": ["input:work_content"]}],
                  "warnings": [f"提示{i}" for i in range(100)]}
        self.app.state.service.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}))
        result = self.client.post("/api/reports/daily/generate", json={
            "report_date": "2026-10-19", "work_content": "完成评审", "file_ids": [file["id"]]})
        self.assertEqual(result.status_code, 200)
        generated = result.json()
        self.assertEqual(len(generated["warnings"]), 100)
        self.assertIn("另有", generated["warnings"][-1])
        saved = self.client.put("/api/reports/daily/2026-10-19", json={
            "points": generated["items"], "warnings": generated["warnings"], "generation_status": generated["status"]})
        self.assertEqual(saved.status_code, 200, saved.text)

    def test_weekly_uses_explicit_source_ids_and_accepts_daily_id_format(self):
        self.save("2026-10-19")
        payloads = []

        def weekly_response(request):
            payload = json.loads(json.loads(request.content)["messages"][1]["content"])
            payloads.append(payload)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "status": "ok", "items": [{"title": "完成需求评审", "source_refs": ["daily:2026-10-19#1"]}],
                "warnings": []})}}]})

        self.app.state.service.transport = httpx.MockTransport(weekly_response)
        result = self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(payloads[0]["daily_reports"][0]["points"][0]["source_ref"], "D1")
        self.assertNotIn("source_refs", payloads[0]["daily_reports"][0]["points"][0])
        self.assertIn("D1", payloads[0]["available_source_refs"])
        self.assertEqual(result.json()["items"][0]["source_refs"], ["daily:daily:2026-10-19#1"])

    def test_weekly_missing_source_refs_are_corrected_once(self):
        self.save("2026-10-19")
        for initial in [None, [], ["input:work_content"]]:
            with self.subTest(initial=initial):
                payloads = []

                def weekly_response(request):
                    payload = json.loads(json.loads(request.content)["messages"][1]["content"])
                    payloads.append(payload)
                    refs = ["D1"] if "citation_correction" in payload else initial
                    point = {"title": "完成需求评审"}
                    if refs is not None:
                        point["source_refs"] = refs
                    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                        "status": "ok", "items": [point], "warnings": []})}}]})

                self.app.state.service.transport = httpx.MockTransport(weekly_response)
                result = self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(len(payloads), 2)
                self.assertIn("citation_correction", payloads[1])
                self.assertEqual(result.json()["items"][0]["source_refs"], ["daily:daily:2026-10-19#1"])

    def test_weekly_correction_does_not_accept_invented_or_other_week_sources(self):
        self.save("2026-10-19")
        for invalid in [[], ["D999"], ["daily:2026-10-26#1"]]:
            with self.subTest(invalid=invalid):
                calls = []

                def weekly_response(request):
                    calls.append(request)
                    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                        "status": "ok", "items": [{"title": "无效结果", "source_refs": invalid}], "warnings": []})}}]})

                self.app.state.service.transport = httpx.MockTransport(weekly_response)
                result = self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"})
                self.assertEqual(result.status_code, 502)
                self.assertEqual(result.json()["error"]["code"], "invalid_evidence_references")
                self.assertIn("自动校正一次", result.json()["error"]["message"])
                self.assertEqual(len(calls), 2)

    def test_weekly_file_source_alias_maps_to_the_correct_fact(self):
        file = self.upload()
        self.client.post("/api/reports/daily/generate", json={"report_date": "2026-10-19", "file_ids": [file["id"]]})
        self.save("2026-10-19", [file["id"]])
        payloads = []

        def weekly_response(request):
            payload = json.loads(json.loads(request.content)["messages"][1]["content"])
            payloads.append(payload)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "status": "ok", "items": [{"title": "完成评审", "source_refs": [" F1 "]}], "warnings": []})}}]})

        self.app.state.service.transport = httpx.MockTransport(weekly_response)
        result = self.client.post("/api/reports/weekly/generate", json={"anchor_date": "2026-10-20"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(payloads), 1)
        self.assertIn("F1", payloads[0]["available_source_refs"])
        self.assertEqual(payloads[0]["file_analyses"][0]["facts"][0]["source_ref"], "F1")
        self.assertEqual(result.json()["items"][0]["source_refs"], [f"file:{file['id']}#f1"])


class ExtractionTests(unittest.TestCase):
    def test_office_text_and_image_extraction(self):
        from docx import Document
        from openpyxl import Workbook
        from PIL import Image
        from pptx import Presentation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc = Document()
            doc.add_paragraph("完成需求评审")
            doc.save(root / "a.docx")
            self.assertIn("完成需求评审", extract(root / "a.docx", "a.docx")["content"])
            workbook = Workbook()
            workbook.active.append(["任务", "状态"])
            workbook.active.append(["评审", "=1+1"])
            workbook.save(root / "a.xlsx")
            self.assertIn("=1+1", extract(root / "a.xlsx", "a.xlsx")["content"])
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = "项目评审"
            deck.save(root / "a.pptx")
            self.assertIn("项目评审", extract(root / "a.pptx", "a.pptx")["content"])
            Image.new("RGB", (10, 10)).save(root / "a.png")
            self.assertTrue(extract(root / "a.png", "a.png")["image"].startswith("data:image/jpeg;base64,"))

    def test_natural_week_convention(self):
        self.assertEqual(week_label(date(2026, 10, 20)), "10月第4周")
        self.assertEqual(week_label(date(2026, 11, 1)), "11月第1周")
        self.assertEqual(tuple(map(str, week_range(date(2026, 11, 1)))), ("2026-10-26", "2026-11-01"))

    def test_cross_month_week_has_one_owner_and_label(self):
        for anchor, expected in [
            (date(2027, 8, 29), "8月第5周"),
            (date(2027, 8, 30), "9月第1周"),
            (date(2027, 9, 1), "9月第1周"),
            (date(2026, 10, 26), "11月第1周"),
            (date(2026, 11, 30), "12月第1周"),
            (date(2026, 12, 28), "1月第1周"),
            (date(2027, 1, 4), "1月第2周"),
            (date(2027, 2, 28), "2月第4周"),
        ]:
            with self.subTest(anchor=anchor):
                start, _ = week_range(anchor)
                for offset in range(7):
                    self.assertEqual(week_label(start + timedelta(days=offset)), expected)


if __name__ == "__main__":
    unittest.main()
