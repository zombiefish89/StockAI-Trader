"""统一的大模型调用封装，支持 OpenAI / Qwen / Gemini 等。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:  # pragma: no cover - requests 未安装
    requests = None  # type: ignore

logger = logging.getLogger(__name__)


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
        prompt = build_single_analysis_prompt(payload, mode)
        return self._chat(prompt)

    # --- Internal helpers ---

    def _chat(self, prompt: str) -> str:
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

    def _call_openai(self, prompt: str) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OPENAI_API_KEY 未配置")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = self.model or os.getenv("OPENAI_MODEL", "gpt-5")

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个专业的证券分析师，用简洁中文总结关键机会和风险。",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "600")),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
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

    def _call_qwen(self, prompt: str) -> str:
        api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise LLMError("QWEN_API_KEY/DASHSCOPE_API_KEY 未配置")
        model = self.model or os.getenv("QWEN_MODEL", "qwen3-max")
        base_url = os.getenv(
            "QWEN_ENDPOINT",
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        )

        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "你是专业的证券分析师，用简洁中文总结宏观与机会。",
                    },
                    {"role": "user", "content": prompt},
                ]
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
                                    fragment = item.get("text") or item.get("content")
                                    if isinstance(fragment, str) and fragment.strip():
                                        fragments.append(fragment.strip())
                                elif isinstance(item, str) and item.strip():
                                    fragments.append(item.strip())
                            if fragments:
                                return "\n".join(fragments).strip()
                        elif isinstance(content, str) and content.strip():
                            return content.strip()
        raise LLMError(f"Qwen 响应解析失败: {data}")

    def _call_gemini(self, prompt: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("GEMINI_API_KEY 未配置")
        model = self.model or os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        base_url = os.getenv(
            "GEMINI_BASE_URL",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ]
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
    ticker = payload.get("ticker")
    timeframe = payload.get("timeframe")
    decision = payload.get("decision", {})
    quote = payload.get("quote") or {}
    macro = payload.get("macro") or {}

    mode = (mode or "short_term").lower()
    mode_title = "短线交易分析" if mode == "short_term" else "中长期投资评估"

    prompt_lines = [
        f"请作为专业证券分析师，对 {ticker} 进行{mode_title}。",
        f"分析周期：{timeframe}",
        f"模型决策数据：{json.dumps(decision, ensure_ascii=False)}",
    ]

    if mode == "short_term":
        prompt_lines.append(
            "请重点参考技术面指标、趋势强弱、资金和情绪线索，快速给出：1) 操作结论；2) 关键技术要点；3) 风险控制与止盈止损建议。"
        )
    else:
        prompt_lines.extend(
            [
                "以下为基本面快照：" + json.dumps(quote, ensure_ascii=False),
                "宏观/行业参考：" + json.dumps(macro, ensure_ascii=False),
                "请综合技术走势、估值、成长性、行业地位与宏观环境，分条说明：结论、主要驱动与催化、潜在风险与监控要点。",
            ]
        )

    return "\n".join(prompt_lines)
