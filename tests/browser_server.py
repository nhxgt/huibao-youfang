"""Isolated UI test server; temporary data and a deterministic fake provider."""
import json
import os
import tempfile
from pathlib import Path

import httpx
import uvicorn

from backend.app import create_app


def fake_provider(request):
    messages = json.loads(request.content)["messages"]
    content = messages[1]["content"]
    payload = json.loads(content if isinstance(content, str) else content[0]["text"])
    if "file_id" in payload:
        answer = {
            "status": "ok", "file_id": payload["file_id"], "file_name": payload["file_name"],
            "summary": "整理工作材料", "facts": [{"id": "f1", "content": "完成需求评审",
                "category": "成果", "work_status": "已完成", "certainty": "明确"}], "warnings": []}
    else:
        if "daily_reports" in payload:
            ref = payload["daily_reports"][0]["points"][0]["source_ref"]
            title = "汇总本周工作"
        elif payload["work_content"]:
            ref, title = "input:work_content", "整理本日工作"
        else:
            ref, title = f"file:{payload['file_analyses'][0]['file_id']}#f1", "整理本日工作"
        answer = {"status": "ok", "items": [{"title": title, "text": "根据输入材料整理工作成果。",
                                               "source_refs": [ref]}], "warnings": []}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)},
                                                "finish_reason": "stop"}]})


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="report-ui-test-") as directory:
        app = create_app(Path(directory), httpx.MockTransport(fake_provider))
        app.state.store.set_setting("model", {"name": "fixture-model", "base_url": "https://test.invalid/v1"})
        app.state.service.api_key = "test-only-key"
        uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("TEST_PORT", "8001")), access_log=False)
