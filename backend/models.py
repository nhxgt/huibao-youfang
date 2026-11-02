from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .key_validation import INVALID_KEY_MESSAGE, valid_api_key


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Profile(InputModel):
    name: str = Field(default="", max_length=30)
    role: str = Field(default="", max_length=30)
    dept: str = Field(default="", max_length=60)


class ModelSettings(InputModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr | None = None
    clear_api_key: bool = False

    @field_validator("base_url")
    @classmethod
    def check_base_url(cls, value: str) -> str:
        u = urlsplit(value)
        try:
            _ = u.port
        except ValueError:
            raise ValueError("Base URL 端口无效") from None
        if (u.scheme not in {"https", "http"} or not u.hostname or
                u.username or u.password or u.query or u.fragment):
            raise ValueError("请提供不含账号、查询参数和片段的 HTTP(S) Base URL")
        return value.rstrip("/").removesuffix("/chat/completions").rstrip("/")

    @field_validator("api_key")
    @classmethod
    def check_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            key = value.get_secret_value().strip()
            if key and not valid_api_key(key):
                raise ValueError(INVALID_KEY_MESSAGE)
            return SecretStr(key) if key else None
        return value


class Point(InputModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=5000)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class GenerationResult(InputModel):
    status: Literal["ok", "partial", "insufficient_information"]
    items: list[Point] = Field(max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_result(self):
        if self.status == "insufficient_information" and self.items:
            raise ValueError("信息不足时不能返回汇报事项")
        if self.status != "insufficient_information" and not self.items:
            raise ValueError("没有事项时应返回信息不足")
        return self


class Fact(InputModel):
    id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=5000)
    category: Literal["成果", "进展", "问题", "计划", "背景"]
    work_status: Literal["已完成", "进行中", "待确认", "计划开展", "未说明"]
    responsibility: str = Field(default="未说明", max_length=300)
    locator: str = Field(default="正文，位置未提供", max_length=500)
    certainty: Literal["明确", "不确定"] = "明确"


class FileAnalysis(InputModel):
    status: Literal["ok", "partial", "unreadable"]
    file_id: str
    file_name: str
    document_stage: Literal["草稿", "评审版", "定稿", "未说明"] = "未说明"
    summary: str = Field(default="", max_length=5000)
    facts: list[Fact] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class DailyGeneration(InputModel):
    report_date: date
    work_content: str = Field(default="", max_length=20000)
    file_ids: list[str] = Field(default_factory=list, max_length=30)
    requirements: str = Field(default="", max_length=4000)
    previous_report: list[Point] = Field(default_factory=list, max_length=50)


class WeeklyGeneration(InputModel):
    anchor_date: date
    requirements: str = Field(default="", max_length=4000)
    previous_report: list[Point] = Field(default_factory=list, max_length=50)


class SaveReport(InputModel):
    points: list[Point] = Field(min_length=1, max_length=50)
    notes: str = Field(default="", max_length=20000)
    file_ids: list[str] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    generation_status: Literal["ok", "partial"] = "ok"
    expected_revision: int | None = Field(default=None, ge=0)
    source_revisions: dict[str, int] | None = None


class Draft(InputModel):
    report_date: date
    notes: str = Field(default="", max_length=20000)
    file_ids: list[str] = Field(default_factory=list, max_length=30)
    points: list[Point] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    generation_status: Literal["ok", "partial"] = "ok"
    source_revisions: dict[str, int] | None = None


class ArchiveRequest(InputModel):
    kind: Literal["daily", "weekly"]
    report_date: date
    file_ids: list[str] = Field(default_factory=list, max_length=200)
