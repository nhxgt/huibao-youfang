import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError

from .key_validation import INVALID_KEY_MESSAGE, valid_api_key

PROMPT_DIR = Path(__file__).parent / "prompts"


class ModelError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


@dataclass(frozen=True)
class Connection:
    model: str
    base_url: str
    api_key: str


class ModelClient:
    def __init__(self, connection: Connection, transport=None):
        self.connection, self.transport = connection, transport

    async def call(self, task, payload, schema, image=None):
        if not valid_api_key(self.connection.api_key):
            raise ModelError("invalid_api_key", INVALID_KEY_MESSAGE, 422)
        common = (PROMPT_DIR / "common.txt").read_text(encoding="utf-8")
        prompt = (PROMPT_DIR / f"{task}.txt").read_text(encoding="utf-8")
        prompt += "\n必须遵守以下 JSON Schema：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        text = json.dumps(payload, ensure_ascii=False)
        content = text if image is None else [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image}},
        ]
        body = {"model": self.connection.model, "stream": False,
                "messages": [{"role": "system", "content": common + "\n\n" + prompt},
                             {"role": "user", "content": content}]}
        headers = {"Authorization": f"Bearer {self.connection.api_key}", "Content-Type": "application/json"}
        try:
            async with asyncio.timeout(150):
                async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15),
                                             follow_redirects=False, trust_env=False,
                                             transport=self.transport) as client:
                    async with client.stream("POST", self.connection.base_url + "/chat/completions",
                                             json=body, headers=headers) as response:
                        if response.status_code in {401, 403}:
                            raise ModelError("model_auth_failed", "模型服务拒绝认证，请检查 API Key 和模型权限。")
                        if response.status_code == 429:
                            raise ModelError("model_rate_limited", "模型服务额度不足或请求过于频繁，请稍后重试。", 429)
                        if response.status_code >= 300:
                            raise ModelError("model_request_failed",
                                             f"模型服务返回 HTTP {response.status_code}，请检查模型名称、Base URL 和服务状态。")
                        chunks, length = [], 0
                        async for chunk in response.aiter_bytes():
                            length += len(chunk)
                            if length > 2 * 1024 * 1024:
                                raise ModelError("model_response_too_large", "模型返回内容过长，请减少输入材料。")
                            chunks.append(chunk)
                        result = json.loads(b"".join(chunks))
            if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
                raise ValueError("missing choices")
            choice = result["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise ValueError("invalid choice")
            if choice.get("finish_reason") == "length":
                raise ModelError("model_output_truncated", "模型输出被截断，请减少材料或换用支持更长输出的模型。")
            answer = choice["message"]["content"]
            if isinstance(answer, list):
                if any(not isinstance(part, dict) for part in answer):
                    raise ValueError("invalid content parts")
                answer = "".join(p.get("text", "") for p in answer if p.get("type") == "text")
            if not isinstance(answer, str):
                raise ValueError("missing text")
            answer = answer.strip()
            fence = chr(96) * 3
            if answer.startswith(fence) and answer.endswith(fence):
                answer = answer.split("\n", 1)[1].rsplit(fence, 1)[0].strip()
            return schema.model_validate(json.loads(answer))
        except ModelError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise ModelError("model_timeout", "模型响应超时，请稍后重试或减少附件数量。", 504) from None
        except httpx.RequestError:
            raise ModelError("model_unreachable", "无法连接模型服务，请检查 Base URL 和网络。") from None
        except (ValueError, KeyError, IndexError, TypeError, ValidationError):
            raise ModelError("invalid_model_response", "模型没有返回有效的结构化结果，请重试或更换模型。") from None
