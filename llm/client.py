"""统一的大模型调用封装，支持 OpenAI / Qwen / Gemini 等。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, List, Union

try:
    import requests
except ImportError:  # pragma: no cover - requests 未安装
    requests = None  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "你是一名严格、审慎的证券分析师与投研助理。你只依据提供的结构化数据做出分析，"
    "所有结论必须注明对应的证据字段，不得臆造或引用外部数据。如数据缺失或冲突，需明确标注并说明影响。"
    "输出始终包含两部分：\n1) 中文可读报告（Markdown）；\n2) 机器可解析 JSON，与报告信息一致。"
)

MODE_PROMPT_FAST = (
    "【分析模式：FAST】目标：快速给出可执行的结论草案；字数 ≤400 字；步骤 ≤6；"
    "优先引用最新行情、近7~30日价量与情绪信号；选择最关键的3~5个指标；标记缺失数据。"
)

MODE_PROMPT_DEEP = (
    "【分析模式：DEEP】目标：系统化研究报告；字数 1200~2000 字；步骤 ≤16；"
    "覆盖估值、成长、质量、技术、资金、情绪、宏观行业；必须给出牛/中/熊场景及监控清单。"
)


class LLMError(RuntimeError):
    """模型调用失败。"""


class LLMNotConfigured(LLMError):
    """环境未配置模型信息。"""


@dataclass
class LLMClient:
    provider: str
    model: Optional[str] = None
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "LLMClient":
        provider = os.getenv("LLM_PROVIDER")
        if not provider:
            if os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"):
                provider = "qwen"
            elif os.getenv("OPENAI_API_KEY"):
                provider = "openai"
            elif os.getenv("GEMINI_API_KEY"):
                provider = "gemini"

        if not provider:
            raise LLMNotConfigured("LLM_PROVIDER 未配置，也未检测到可用的 API Key")

        provider = provider.lower()
        default_models = {
            "openai": "gpt-5",
            "chatgpt": "gpt-5",
            "qwen": "qwen3-max",
            "dashscope": "qwen3-max",
            "gemini": "gemini-2.5-pro",
            "google": "gemini-2.5-pro",
        }
        model = os.getenv("LLM_MODEL") or default_models.get(provider)
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        return cls(provider=provider, model=model, timeout=timeout)

    def summarize_daily_report(self, payload: Dict[str, Any]) -> str:
        prompt = build_daily_report_prompt(payload)
        return self._chat(prompt)

    def summarize_batch_analysis(self, payload: Dict[str, Any]) -> str:
        prompt = build_batch_analysis_prompt(payload)
        return self._chat(prompt)

    def summarize_single_analysis(self, payload: Dict[str, Any], mode: str) -> str:
        messages = build_single_analysis_prompt(payload, mode)
        return self._chat(messages)

    # --- Internal helpers ---

    def _chat(self, prompt: Union[str, Sequence[Dict[str, str]]]) -> str:
        if requests is None:
            raise LLMError("requests 模块缺失，无法调用 LLM")

        provider = self.provider
        if provider in {"openai", "chatgpt"}:
            return self._call_openai(prompt)
        if provider in {"qwen", "dashscope"}:
            return self._call_qwen(prompt)
        if provider in {"gemini", "google"}:
            return self._call_gemini(prompt)
        raise LLMError(f"暂不支持的 LLM 提供商: {provider}")

    def _call_openai(self, prompt: Union[str, Sequence[Dict[str, str]]]) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OPENAI_API_KEY 未配置")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = self.model or os.getenv("OPENAI_MODEL", "gpt-5")

        messages: List[Dict[str, str]]
        messages = _normalize_messages(prompt)

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1000")),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.6")),
        }

        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"OpenAI 请求失败: {resp.text}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise LLMError(f"OpenAI 响应解析失败: {data}") from exc

    def _call_qwen(self, prompt: Union[str, Sequence[Dict[str, str]]]) -> str:
        api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise LLMError("QWEN_API_KEY/DASHSCOPE_API_KEY 未配置")
        model = self.model or os.getenv("QWEN_MODEL", "qwen3-max")
        base_url = os.getenv(
            "QWEN_ENDPOINT",
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        )

        messages = _normalize_messages(prompt)
        payload = {
            "model": model,
            "input": {
                "messages": messages,
            },
        }
        resp = requests.post(
            base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"Qwen 请求失败: {resp.text}")
        data = resp.json()
        output = data.get("output") if isinstance(data, dict) else None
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            choices = output.get("choices")
            if isinstance(choices, list) and choices:
                choice = choices[0] or {}
                if isinstance(choice, dict):
                    choice_text = choice.get("text")
                    if isinstance(choice_text, str) and choice_text.strip():
                        return choice_text.strip()
                    message = choice.get("message")
                    if isinstance(message, dict):
                        msg_text = message.get("text")
                        if isinstance(msg_text, str) and msg_text.strip():
                            return msg_text.strip()
                        content = message.get("content")
                        if isinstance(content, list):
                            fragments: list[str] = []
                            for item in content:
                                if isinstance(item, dict):
                                    fragment = item.get(
                                        "text") or item.get("content")
                                    if isinstance(fragment, str) and fragment.strip():
                                        fragments.append(fragment.strip())
                                elif isinstance(item, str) and item.strip():
                                    fragments.append(item.strip())
                            if fragments:
                                return "\n".join(fragments).strip()
                        elif isinstance(content, str) and content.strip():
                            return content.strip()
        raise LLMError(f"Qwen 响应解析失败: {data}")

    def _call_gemini(self, prompt: Union[str, Sequence[Dict[str, str]]]) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("GEMINI_API_KEY 未配置")
        model = self.model or os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        base_url = os.getenv(
            "GEMINI_BASE_URL",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        )
        messages = _normalize_messages(prompt)
        contents = []
        for message in messages:
            role = message.get("role", "user")
            text = message.get("content", "")
            mapped_role = "user"
            if role == "assistant":
                mapped_role = "model"
            elif role == "system":
                mapped_role = "user"
                text = "[SYSTEM]\n" + text
            elif role == "developer":
                mapped_role = "user"
                text = "[DEVELOPER]\n" + text
            contents.append({"role": mapped_role, "parts": [{"text": text}]})

        payload = {
            "contents": contents
        }
        resp = requests.post(
            base_url,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"Gemini 请求失败: {resp.text}")
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Gemini 响应解析失败: {data}") from exc


def build_daily_report_prompt(payload: Dict[str, Any]) -> str:
    indices = payload.get("macro", {}).get("indices", {})
    highlights = payload.get("macro", {}).get("highlights", [])
    risks = payload.get("macro", {}).get("risks", [])
    opportunities = payload.get("opportunities", {}).get("candidates", [])
    summary = payload.get("overview")

    prompt = [
        "以下是股票分析系统生成的结构化数据，请用简洁的中文总结当日宏观环境与交易机会，分成‘宏观点评’、‘机会推荐’、‘风险提示’三段，每段最多 3 句话。",
        f"宏观概览：{summary}",
        f"指数数据：{json.dumps(indices, ensure_ascii=False)}",
        f"宏观亮点：{json.dumps(highlights, ensure_ascii=False)}",
        f"宏观风险：{json.dumps(risks, ensure_ascii=False)}",
    ]
    prompt.append(f"机会候选：{json.dumps(opportunities, ensure_ascii=False)}")
    return "\n".join(prompt)


def build_batch_analysis_prompt(payload: Dict[str, Any]) -> str:
    scope = list(payload.get("results", {}).keys())
    macro = payload.get("macro", {})
    opportunities = payload.get("opportunities", {}).get("candidates", [])
    prompt = [
        "请基于以下批量分析结果，输出简明扼要的‘整体判断’、‘重点标的’、‘风险提示’三段文字。",
        f"涉及股票：{scope}",
        f"宏观摘要：{json.dumps(macro, ensure_ascii=False)}",
        f"机会候选：{json.dumps(opportunities, ensure_ascii=False)}",
        f"个股详情：{json.dumps(payload.get('results', {}), ensure_ascii=False)}",
    ]
    return "\n".join(prompt)


def build_single_analysis_prompt(payload: Dict[str, Any], mode: str) -> str:
    mode_norm = (mode or "fast").strip().lower()
    mode_upper = "FAST" if mode_norm == "fast" else "DEEP"

    ticker = payload.get("ticker")
    timeframe = payload.get("timeframe")
    indicators = payload.get("indicators", {})
    quote = payload.get("quote") or {}
    macro = payload.get("macro") or {}

    data_quality = {
        "missing": [],
        "latency": [],
    }

    if not indicators:
        data_quality["missing"].append("indicators")
    if not quote:
        data_quality["missing"].append("quote_snapshot")
    if not macro:
        data_quality["missing"].append("macro")

    context = {
        "meta": {
            "ticker": ticker,
            "timeframe": timeframe,
            "mode": mode_upper,
        },
        "indicators": indicators,
        "quote": quote,
        "macro": macro,
        "data_quality": data_quality,
    }

    context_json = json.dumps(context, ensure_ascii=False, default=str)

    user_prompt = (
        f"请对 {ticker} 进行{('快速' if mode_upper=='FAST' else '深度')}分析。"
        f"\n数据上下文(JSON)：\n{context_json}\n\n"
        "请严格遵循以下输出格式：\n"
        "1) 中文报告：使用 Markdown，包含 结论 / 信号总览 / 投资逻辑 / 情景与计划 / 风险 / 数据质量，"
        "并在每条关键判断后标注“（证据：字段名）”。\n"
        "2) JSON：字段应包括 summary、signals、thesis、scenarios、risks、data_quality，与报告内容一致，"
        "每项的 evidence 列出所引用的字段。"
    )

    mode_prompt = MODE_PROMPT_FAST if mode_upper == "FAST" else MODE_PROMPT_DEEP

    messages = [
        {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        {"role": "developer", "content": mode_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return messages


def _normalize_messages(prompt: Union[str, Sequence[Dict[str, str]]]) -> List[Dict[str, str]]:
    if isinstance(prompt, str):
        return [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    normalized: List[Dict[str, str]] = []
    allowed_roles = {"system", "user", "assistant"}
    for message in prompt:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "user") or "user").lower()
        content = message.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        if role not in allowed_roles:
            prefix = f"[{role.upper()}]\n"
            role = "user"
            content = prefix + content
        normalized.append({"role": role, "content": content})
    if not normalized:
        normalized = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": ""},
        ]
    return normalized
