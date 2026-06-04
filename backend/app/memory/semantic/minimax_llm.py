"""mem0 LLM subclass that strips MiniMax-M3 ``<think>`` blocks (ADR-006).

mem0's ``infer=True`` fact-extraction calls the configured LLM and JSON-parses
the returned content. MiniMax-M3 is a reasoning model that prepends
``<think>...</think>`` to its content, which breaks that parse (mem0 logs
``Error in new_retrieved_facts: Expecting value: line 1 column 1`` and extracts
0 facts). This subclass strips the reasoning block from the content before mem0
parses it.

Registered with mem0's ``LlmFactory`` under the ``openai`` provider by
``mem0_config`` (this process only uses mem0 for WeatherFlow — same rationale as
the SiliconFlow embedder override).
"""

from __future__ import annotations

import re
from typing import Any

from mem0.llms.openai import OpenAILLM

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    out = _THINK_RE.sub("", text).strip()
    low = out.lower()
    if "<think>" in low:  # stray, unterminated reasoning block
        out = out[: low.rfind("<think>")].strip()
    return out


class MiniMaxLLM(OpenAILLM):
    def _parse_response(self, response: Any, tools: Any):
        out = super()._parse_response(response, tools)
        if isinstance(out, str):
            return _strip_think(out)
        if isinstance(out, dict) and isinstance(out.get("content"), str):
            out["content"] = _strip_think(out["content"])
        return out


__all__ = ["MiniMaxLLM"]
