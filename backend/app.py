import asyncio
import hashlib
import mimetypes
import os
import re
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .llm import ModelError
from .credentials import CredentialError
from .models import ArchiveRequest, DailyGeneration, Draft, ModelSettings, Profile, SaveReport, WeeklyGeneration
from .service import Service, ServiceError, week_range
from .store import ConflictError, Store, timestamp
from .paths import RESOURCE_ROOT, resolve_data_dir

ROOT = RESOURCE_ROOT
MAX_FILE = 50 * 1024 * 1024


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = MAX_FILE if scope["path"] == "/api/files" else 1024 * 1024
        consumed = 0

        async def limited_receive():
            nonlocal consumed
            event = await receive()
            consumed += len(event.get("body", b""))
            if consumed > limit:
                raise BodyTooLarge()
            return event
        await self.app(scope, limited_receive, send)


def create_app(data_dir=None, model_transport=None):
    store = Store(resolve_data_dir(data_dir))
    service = Service(store, model_transport)
    def documented_header(x_work_report: str = Header(default="1", description="本地界面写操作标记，固定填写 1")):
        pass

    app = FastAPI(title="汇报有方 API", version="1.0.0", dependencies=[Depends(documented_header)],
                  description="个人日报、周报与成果归档接口。写操作须携带 X-Work-Report: 1。API Key 使用当前 Windows 用户的 DPAPI 加密保存，查询接口不返回明文。")
    app.state.service, app.state.store = service, store
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_guard(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if request.headers.get("x-work-report") != "1" or (origin and origin != expected):
                return JSONResponse({"error": {"code": "invalid_origin", "message": "请从本服务页面发起操作。"}}, status_code=403)
        if request.headers.get("content-length", "").isdigit():
            limit = MAX_FILE if request.url.path == "/api/files" else 1024 * 1024
            if int(request.headers["content-length"]) > limit:
                return JSONResponse({"error": {"code": "body_too_large", "message": "上传文件超过 50 MB 或请求内容过大。"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ServiceError)
    @app.exception_handler(ModelError)
    async def service_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(CredentialError)
    async def credential_error(request, exc):
        return JSONResponse({"error": {"code": "credential_storage_failed",
                                      "message": "无法安全保存 API Key，请检查当前 Windows 账户和数据目录权限。"}}, status_code=503)

    @app.exception_handler(BodyTooLarge)
    async def large_body(request, exc):
        return JSONResponse({"error": {"code": "body_too_large", "message": "文件或请求内容过大。"}}, status_code=413)

    @app.exception_handler(ConflictError)
    async def conflict(request, exc):
        return JSONResponse({"error": {"code": "revision_conflict", "message": str(exc)}}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo rejected inputs: they may include API credentials.
        fields = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "请求参数有误，请检查填写内容。",
                                      "fields": fields}}, status_code=422)

    @app.get("/", include_in_schema=False)
    @app.get("/work-report-prototype.html", include_in_schema=False)
    def frontend():
        return FileResponse(ROOT / "work-report-prototype.html", media_type="text/html",
                            headers={"Content-Security-Policy":
                                     "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                     "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                                     "connect-src 'self'; object-src 'none'; frame-ancestors 'none'"})

    @app.get("/assets/app.js", include_in_schema=False)
    @app.get("/frontend/app.js", include_in_schema=False)
    def javascript():
        return FileResponse(ROOT / "frontend" / "app.js", media_type="text/javascript")

    @app.get("/api/health", tags=["系统"])
    def health():
        return {"status": "ok", "version": "1.0.0", "mode": "local-single-user"}

    @app.get("/api/bootstrap", tags=["系统"])
    def bootstrap():
        return {"profile": service.profile(), "model": service.settings(),
                "reports": store.search_reports(limit=300)["items"]}

    @app.get("/api/profile", tags=["设置"])
    def profile():
        return service.profile()

    @app.put("/api/profile", tags=["设置"])
    def save_profile(data: Profile):
        if not data.name or not data.role:
            raise ServiceError("profile_required", "姓名与岗位为必填项。", 422)
        store.set_setting("profile", data.model_dump())
        return service.profile()

    @app.get("/api/model-settings", tags=["设置"])
    def model_settings():
        return service.settings()

    @app.put("/api/model-settings", tags=["设置"])
    def save_model(data: ModelSettings):
        return service.save_model_settings(data)

    @app.delete("/api/model-settings/key", tags=["设置"])
    def clear_model_key():
        return service.clear_model_key()

    @app.post("/api/model-settings/test", tags=["设置"])
    async def test_model():
        # Test the actual structured-output capability, not just /models.
        from .models import GenerationResult
        result = await service.model_client().call("daily", {
            "report_date": str(date.today()), "profile": service.profile(),
            "work_content": "完成模型连接测试。", "file_analyses": [], "requirements": "",
            "previous_report": []
        }, GenerationResult)
        service.validate_result(result, {"input:work_content"}, [])
        return {"status": "ok", "message": "模型连接与结构化输出测试通过。"}

    @app.post("/api/files", tags=["成果文件"], status_code=201)
    async def upload(request: Request, report_date: date = Query(),
                     filename: str = Query(min_length=1, max_length=255)):
        """上传原始文件字节，Content-Type: application/octet-stream；非 multipart。"""
        if (filename in {".", ".."} or re.search(r'[/\\\x00-\x1f]', filename)):
            raise ServiceError("invalid_filename", "文件名不能包含路径或控制字符。", 422)
        file_id, total, digest = uuid4().hex, 0, hashlib.sha256()
        destination = store.files_dir / file_id
        try:
            with destination.open("xb") as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_FILE:
                        raise BodyTooLarge()
                    digest.update(chunk)
                    output.write(chunk)
            if not total:
                raise ServiceError("empty_file", "不能上传空文件。", 422)
            return store.add_file({"id": file_id, "name": filename, "date": str(report_date), "size": total,
                                   "media_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
                                   "sha256": digest.hexdigest(), "created_at": timestamp()})
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    @app.get("/api/files", tags=["成果文件"])
    def files(report_date: date):
        return {"items": store.list_files(str(report_date))}

    @app.get("/api/files/{file_id}/download", tags=["成果文件"])
    def download(file_id: str):
        item = service.files([file_id])[0]
        return FileResponse(store.files_dir / item["id"], filename=item["name"], media_type="application/octet-stream")

    @app.get("/api/weeks/{anchor_date}/sources", tags=["周报"])
    def week_sources(anchor_date: date):
        return service.weekly_sources(anchor_date)

    async def generation(task):
        try:
            async with asyncio.timeout(420):
                async with service.generation_slots:
                    return await task()
        except TimeoutError:
            raise ServiceError("generation_timeout", "生成耗时过长，请减少成果文件后重试。", 504) from None

    @app.post("/api/reports/daily/generate", tags=["日报"])
    async def daily(data: DailyGeneration):
        return await generation(lambda: service.daily(data))

    @app.post("/api/reports/weekly/generate", tags=["周报"])
    async def weekly(data: WeeklyGeneration):
        return await generation(lambda: service.weekly(data))

    @app.get("/api/reports", tags=["历史汇报"])
    def reports(kind: Literal["daily", "weekly"] | None = None, start: date | None = None,
                end: date | None = None, q: str = Query(default="", max_length=200),
                limit: int = Query(default=100, ge=1, le=300), offset: int = Query(default=0, ge=0),
                on_date: date | None = Query(default=None, description="按日期查找当天日报及汇报周期包含该日的周报")):
        return store.search_reports(kind, str(start) if start else None, str(end) if end else None, q,
                                    str(on_date) if on_date else None, limit, offset)

    @app.get("/api/reports/{kind}/{report_date}", tags=["历史汇报"])
    def report(kind: Literal["daily", "weekly"], report_date: date):
        start = week_range(report_date)[0] if kind == "weekly" else report_date
        item = store.report(kind, str(start))
        if not item:
            raise ServiceError("report_not_found", "该日期还没有已保存的汇报。", 404)
        return item

    @app.put("/api/reports/{kind}/{report_date}", tags=["历史汇报"])
    def save(kind: Literal["daily", "weekly"], report_date: date, data: SaveReport):
        profile = service.profile(required=True)
        if kind == "daily":
            attached = service.files(data.file_ids, report_date)
            start = end = report_date
        else:
            start, end = week_range(report_date)
            sources = service.weekly_sources(report_date)
            attached = sources["files"]
            if not sources["daily_reports"]:
                raise ServiceError("no_daily_reports", "该周没有可关联的日报。", 422)
            source_revisions = {r["id"]: r["revision"] for r in sources["daily_reports"]}
            if data.source_revisions is not None and data.source_revisions != source_revisions:
                raise ServiceError("weekly_sources_changed", "日报来源已更新，请重新生成周报后再保存。", 409)
        content = {"profile": profile, "points": [p.model_dump() for p in data.points], "notes": data.notes,
                   "warnings": data.warnings, "generation_status": data.generation_status}
        if kind == "weekly":
            content["source_revisions"] = source_revisions
        return store.save_report(kind, str(report_date), str(start), str(end), content,
                                 [f["id"] for f in attached], data.expected_revision,
                                 data.source_revisions if kind == "weekly" else None)

    @app.get("/api/drafts/{kind}/{report_date}", tags=["草稿"])
    def draft(kind: Literal["daily", "weekly"], report_date: date):
        key = week_range(report_date)[0] if kind == "weekly" else report_date
        return {"draft": store.get_draft(kind, str(key))}

    @app.put("/api/drafts/{kind}/{report_date}", tags=["草稿"])
    def save_draft(kind: Literal["daily", "weekly"], report_date: date, data: Draft):
        if data.report_date != report_date:
            raise ServiceError("draft_date_mismatch", "草稿日期与接口日期不一致。", 422)
        service.files(data.file_ids, report_date if kind == "daily" else None)
        content = data.model_dump(mode="json")
        key = week_range(report_date)[0] if kind == "weekly" else report_date
        store.save_draft(kind, str(key), content)
        return {"draft": content}

    @app.post("/api/archives", tags=["成果下载"])
    async def archive(data: ArchiveRequest):
        path, name = await asyncio.to_thread(service.archive, data.kind, data.report_date, data.file_ids)
        return FileResponse(path, filename=name, media_type="application/zip",
                            background=BackgroundTask(path.unlink, missing_ok=True))

    return app


app = create_app()
