import asyncio
import hashlib
import json
import os
import re
import tempfile
import threading
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .extraction import extract
from .credentials import CredentialError, cleared_record, protect_key, unprotect_key
from .key_validation import valid_api_key
from .llm import PROMPT_DIR, Connection, ModelClient, ModelError
from .models import FileAnalysis, GenerationResult, Profile


class ServiceError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def week_range(anchor: date):
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def week_label(anchor: date):
    # A week crossing a month boundary belongs only to the following month.
    anchor = week_range(anchor)[1]
    first = anchor.replace(day=1)
    return f"{anchor.month}月第{(anchor.day - 1 + first.weekday()) // 7 + 1}周"


def clean_name(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).rstrip(". ")[:150] or "未命名"


def member_name(info, position):
    name = Path(info["name"])
    return f"{position:02d}_{clean_name(name.stem)}_{info['date'].replace('-', '')}{clean_name(name.suffix) if name.suffix else ''}"


class Service:
    def __init__(self, store, transport=None):
        self.store, self.transport = store, transport
        self.api_key = ""
        self.key_persisted = False
        self.credential_error = False
        self.settings_lock = threading.RLock()
        self.generation_slots = asyncio.Semaphore(2)
        self.analysis_slots = asyncio.Semaphore(3)
        self._load_credentials()

    def _load_credentials(self):
        self.api_key, self.key_persisted, self.credential_error = "", False, False
        record = self.store.get_setting("model_credentials")
        if record is None:
            self.api_key = os.getenv("WORK_REPORT_API_KEY", "").strip()
        elif isinstance(record, dict) and record.get("cleared") is True:
            self.api_key = ""
        else:
            try:
                model = self.store.get_setting("model", {})
                self.api_key = unprotect_key(record, model.get("base_url", ""))
                self.key_persisted = True
            except CredentialError:
                self.credential_error = True
        if self.api_key and not valid_api_key(self.api_key):
            # Preserve the encrypted record so users can replace it themselves.
            self.api_key, self.key_persisted, self.credential_error = "", False, True

    def save_model_settings(self, data):
        with self.settings_lock:
            current = self.settings()
            key = data.api_key.get_secret_value() if data.api_key else None
            if current["base_url"] and data.base_url != current["base_url"] and not key and not data.clear_api_key:
                raise ServiceError("new_endpoint_requires_key", "修改 Base URL 后请重新填写 API Key，避免将旧凭据发往其他服务。", 422)
            if not key and not self.api_key and not data.clear_api_key:
                raise ServiceError("api_key_required", "首次配置请填写 API Key。", 422)
            next_key = "" if data.clear_api_key else (key or self.api_key)
            record = protect_key(next_key, data.base_url) if next_key else cleared_record()
            self.store.set_settings({"model": {"name": data.name, "base_url": data.base_url},
                                     "model_credentials": record})
            self.api_key, self.key_persisted, self.credential_error = next_key, bool(next_key), False
            return self.settings()

    def clear_model_key(self):
        with self.settings_lock:
            self.store.set_setting("model_credentials", cleared_record())
            self.api_key, self.key_persisted, self.credential_error = "", False, False
            return self.settings()

    def profile(self, required=False):
        profile = Profile.model_validate(self.store.get_setting("profile", {}))
        if required and (not profile.name or not profile.role):
            raise ServiceError("profile_required", "请先在右上角完善姓名和岗位。", 409)
        return profile.model_dump()

    def settings(self):
        with self.settings_lock:
            settings = self.store.get_setting("model", {"name": "", "base_url": ""})
            return {**settings, "has_api_key": bool(self.api_key),
                    "key_persisted": self.key_persisted, "credential_error": self.credential_error,
                    "configured": bool(settings["name"] and settings["base_url"] and self.api_key)}

    def model_client(self):
        with self.settings_lock:
            settings = self.settings()
            if self.credential_error:
                raise ServiceError("invalid_saved_api_key",
                                   "已保存的 API Key 无法读取或格式无效，请在右上角模型 API 设置中重新填写真实密钥。", 409)
            if not settings["configured"]:
                raise ServiceError("model_not_configured", "请先在右上角配置模型名称、API Key 和 Base URL。", 409)
            return ModelClient(Connection(settings["name"], settings["base_url"], self.api_key), self.transport)

    def files(self, ids, report_date=None):
        result = []
        for file_id in dict.fromkeys(ids):
            item = self.store.get_file(file_id)
            if not item or not (self.store.files_dir / file_id).is_file():
                raise ServiceError("file_not_found", "部分成果文件不存在，请重新上传。", 404)
            if report_date and item["date"] != str(report_date):
                raise ServiceError("file_date_mismatch", "成果文件日期与日报日期不一致，请切换日期或重新上传。", 422)
            result.append(item)
        return result

    async def analyze(self, item, client):
        async with self.analysis_slots:
            fingerprint = hashlib.sha256(
                ("extract-v1:" + client.connection.model + ":" + client.connection.base_url).encode() +
                (PROMPT_DIR / "common.txt").read_bytes() + (PROMPT_DIR / "file.txt").read_bytes()
            ).hexdigest()
            cached = self.store.get_file(item["id"], internal=True)
            if cached["analysis"] and cached["analysis_model"] == fingerprint:
                return FileAnalysis.model_validate(cached["analysis"])
            extracted = await asyncio.to_thread(extract, self.store.files_dir / item["id"], item["name"])
            if not extracted["content"].strip() and not extracted["image"]:
                return FileAnalysis(status="unreadable", file_id=item["id"], file_name=item["name"],
                                    warnings=extracted["warnings"] or ["文件没有可分析文字"])
            payload = {"file_id": item["id"], "file_name": item["name"], "report_date": item["date"],
                       "content": extracted["content"], "extraction_notes": extracted["warnings"]}
            try:
                analysis = await client.call("file", payload, FileAnalysis, extracted["image"])
            except ModelError as error:
                if not extracted["image"]:
                    raise
                return FileAnalysis(status="unreadable", file_id=item["id"], file_name=item["name"],
                                    warnings=[f"图片分析失败：{error.message}"])
            analysis.file_id, analysis.file_name = item["id"], item["name"]
            if len({fact.id for fact in analysis.facts}) != len(analysis.facts):
                raise ModelError("invalid_source_ids", "模型返回了重复的文件事实编号，请重试。")
            analysis.warnings = list(dict.fromkeys(analysis.warnings + extracted["warnings"]))
            if any(fact.certainty == "不确定" for fact in analysis.facts):
                analysis.warnings.append("部分事实无法确定，请核对原始材料")
            if analysis.warnings and analysis.status == "ok":
                analysis.status = "partial"
            if analysis.status == "unreadable":
                analysis.facts = []
            self.store.cache_analysis(item["id"], analysis.model_dump(), fingerprint)
            return analysis

    async def analyses(self, files, client, max_files=30):
        if len(files) > max_files:
            raise ServiceError("too_many_analysis_files", f"本次最多分析 {max_files} 个成果文件，请减少所选成果。", 422)
        analyses = await asyncio.gather(*(self.analyze(f, client) for f in files))
        budget, output, warnings = 100000, [], []
        for result in analyses:
            data = result.model_dump()
            used = len(json.dumps(data, ensure_ascii=False))
            if used > budget:
                warnings.append(f"材料《{result.file_name}》超过本次上下文容量，未纳入文字生成，但仍会打包")
                continue
            budget -= used
            output.append(data)
            warnings.extend(f"《{result.file_name}》：{w}" for w in result.warnings)
        return output, warnings

    def validate_result(self, result, allowed_refs, warnings):
        for point in result.items:
            if not point.source_refs or any(ref not in allowed_refs for ref in point.source_refs):
                raise ModelError("invalid_evidence_references", "模型返回的工作要点没有有效来源，请重试。")
        merged = list(dict.fromkeys(result.warnings + warnings))
        result.warnings = merged if len(merged) <= 100 else merged[:99] + [f"另有 {len(merged) - 99} 条材料读取提示，请结合原文件核对。"]
        if result.warnings and result.status == "ok":
            result.status = "partial"
        return result.model_dump()

    async def daily(self, data):
        profile = self.profile(required=True)
        files = self.files(data.file_ids, data.report_date)
        if not data.work_content and not files:
            raise ServiceError("empty_daily_input", "请填写工作内容或上传至少一份成果文件。", 422)
        client = self.model_client()
        analyses, warnings = await self.analyses(files, client)
        if not data.work_content and not any(a["facts"] for a in analyses):
            return GenerationResult(status="insufficient_information", items=[],
                                    warnings=warnings or ["没有可用工作事实，请补充工作内容。"]).model_dump()
        payload = {"report_date": str(data.report_date), "profile": profile,
                   "work_content": data.work_content, "file_analyses": analyses,
                   "requirements": data.requirements,
                   "previous_report": [p.model_dump() for p in data.previous_report]}
        refs = {f"file:{a['file_id']}#{f['id']}" for a in analyses for f in a["facts"]}
        if data.work_content:
            refs.add("input:work_content")
        result = await client.call("daily", payload, GenerationResult)
        return self.validate_result(result, refs, warnings)

    def weekly_sources(self, anchor):
        start, end = week_range(anchor)
        reports = self.store.list_reports("daily", str(start), str(end))
        reports.sort(key=lambda r: r["date"])
        seen, files = set(), []
        for report in reports:
            for item in report["files"]:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    files.append(item)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        missing = [str(start + timedelta(days=i)) for i in range(5)
                   if start + timedelta(days=i) <= today and
                   not any(r["date"] == str(start + timedelta(days=i)) for r in reports)]
        return {"period_start": str(start), "period_end": str(end), "week_label": week_label(anchor),
                "daily_reports": reports, "files": files,
                "coverage": {"dates": [r["date"] for r in reports], "missing_workdays": missing,
                             "period_finished": end < today, "current_date": str(today)}}

    @staticmethod
    def weekly_evidence(reports, analyses):
        """Give the model short, explicit IDs; retain canonical IDs for storage."""
        model_reports, model_analyses, aliases, available = [], [], {}, []
        for report in reports:
            points = []
            for index, point in enumerate(report["points"], 1):
                ref = f"D{len(available) + 1}"
                canonical = f"daily:{report['id']}#{index}"
                aliases.update({ref: canonical, canonical: canonical,
                                f"{report['id']}#{index}": canonical})
                available.append(ref)
                # The daily point's input/file citations are not weekly evidence IDs.
                points.append({"title": point["title"], "text": point.get("text", ""), "source_ref": ref})
            model_reports.append({"id": report["id"], "date": report["date"], "points": points,
                                  "warnings": report.get("warnings", [])})
        file_index = 0
        for analysis in analyses:
            facts = []
            for fact in analysis["facts"]:
                file_index += 1
                ref = f"F{file_index}"
                canonical = f"file:{analysis['file_id']}#{fact['id']}"
                aliases.update({ref: canonical, canonical: canonical})
                available.append(ref)
                facts.append({**fact, "source_ref": ref})
            model_analyses.append({**analysis, "facts": facts})
        return model_reports, model_analyses, aliases, available

    async def weekly(self, data):
        profile = self.profile(required=True)
        sources = self.weekly_sources(data.anchor_date)
        reports = sources["daily_reports"]
        if not reports:
            raise ServiceError("no_daily_reports", "所选周还没有已保存的日报，请先生成并保存日报。", 422)
        client = self.model_client()
        analyses, warnings = await self.analyses(sources["files"], client, max_files=210)
        for report in reports:
            warnings.extend(f"{report['date']} 日报：{w}" for w in report.get("warnings", []))
        if sources["coverage"]["missing_workdays"]:
            warnings.append("缺少工作日日报：" + "、".join(sources["coverage"]["missing_workdays"]))
        if not sources["coverage"]["period_finished"]:
            warnings.append("本周尚未结束，当前周报仅包含已保存日报。")
        model_reports, model_analyses, aliases, available = self.weekly_evidence(reports, analyses)
        payload = {**sources, "profile": profile, "daily_reports": model_reports,
                   "file_analyses": model_analyses, "available_source_refs": available,
                   "current_date": sources["coverage"]["current_date"],
                   "requirements": data.requirements,
                   "previous_report": [p.model_dump() for p in data.previous_report]}
        payload.pop("files")
        if len(json.dumps(payload, ensure_ascii=False)) > 250000:
            raise ServiceError("weekly_context_too_large", "本周日报内容过长，请精简日报后重试。", 422)
        refs = set(aliases.values())
        for attempt in range(2):
            result = await client.call("weekly", payload, GenerationResult)
            for point in result.items:
                point.source_refs = list(dict.fromkeys(aliases.get(ref.strip(), ref.strip()) for ref in point.source_refs))
            try:
                output = self.validate_result(result, refs, warnings)
            except ModelError as error:
                if error.code != "invalid_evidence_references":
                    raise
                if attempt:
                    raise ModelError("invalid_evidence_references",
                                     "模型返回的周报未按要求标注有效来源，自动校正一次后仍未通过。请重试或更换模型。") from None
                payload["citation_correction"] = {
                    "instruction": "上次输出的来源编号无效或缺失。请重新生成，每项 source_refs 必须非空，且只能逐字复制 available_source_refs 中与事项对应的编号。不要沿用日报原有引用，不要编造或推断对应关系。",
                    "invalid_item_numbers": [i for i, point in enumerate(result.items, 1)
                                             if not point.source_refs or any(ref not in refs for ref in point.source_refs)]}
                continue
            output["source_revisions"] = {r["id"]: r["revision"] for r in reports}
            return output

    def archive(self, kind, anchor, file_ids):
        profile = self.profile(required=True)
        if kind == "daily":
            files = self.files(file_ids, anchor)
            prefix = anchor.strftime("%Y%m%d")
        else:
            files = self.files([f["id"] for f in self.weekly_sources(anchor)["files"]])
            prefix = week_label(anchor)
        if not files:
            raise ServiceError("empty_archive", "当前没有成果附件可打包。", 422)
        handle, path = tempfile.mkstemp(suffix=".zip", dir=self.store.temp_dir)
        import os
        os.close(handle)
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for i, item in enumerate(files, 1):
                    archive.write(self.store.files_dir / item["id"], member_name(item, i))
        except Exception:
            Path(path).unlink(missing_ok=True)
            raise
        name = f"{prefix}_{clean_name(profile['role'])}_{clean_name(profile['name'])}_工作汇报.zip"
        return Path(path), name
