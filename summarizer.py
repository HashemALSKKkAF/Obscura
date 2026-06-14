"""
summarizer.py
Map-reduce summarization so the model can process **all** gathered content, not
just what fits in a single prompt.

Single-shot summarization (``llm.generate_summary``) puts every source into one
LLM call. That's fine for a few small pages, but with deep crawl + RAG gathering
many sources the input overruns the model's context window — content is silently
dropped and the report stays short no matter how much was actually found.

This module fixes that with the classic map-reduce pattern:

  1. **Batch**  — pack the gathered content into token-budgeted batches.
  2. **Map**    — ask the model to extract structured intelligence notes from
                  each batch (every source is seen by the model).
  3. **Reduce** — synthesize the notes into the final report using the domain
                  preset. If the notes themselves overflow, reduce recursively.

If everything fits in one batch, it makes a single call — same cost and output
shape as before, so small investigations are unaffected.

The LLM invocation is injected (``llm_call=``) so the whole orchestration is
unit-testable with a fake model — no API key or network required.
"""
from __future__ import annotations

import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from llm import PRESET_PROMPTS, _invoke_with_retry

_logger = logging.getLogger(__name__)

# Rough chars-per-token proxy (avoids a hard tiktoken dependency). Most English
# text is ~4 chars/token; we stay conservative so the prompt + the model's own
# output also fit alongside the content.
CHARS_PER_TOKEN = 4
DEFAULT_BATCH_CHARS = 16_000   # ~4k tokens of content per map call

MAP_SYSTEM_PROMPT = """You are a dark-web OSINT analyst extracting raw intelligence notes.

From the SOURCES below, extract every fact relevant to the investigation query:
indicators, actors, services, prices, leaked data, contact handles, dates, and
relationships. Be exhaustive and concise — bullet points, not prose. Attribute
each note to its source URL. Do NOT write an introduction or conclusion; these
notes are an intermediate step that will be synthesized later.

Investigation query: {query}"""


# ─────────────────────────────────────────────────────────────────────────────
# Content normalisation + batching
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_content(content) -> list[tuple[str, str]]:
    """Coerce the pipeline's content into ``[(source, text), ...]``.

    Accepts the scrape/deep-crawl ``{url: text}`` map, a pre-built RAG context
    string, or anything else (stringified as a single anonymous source).
    """
    if isinstance(content, dict):
        return [(str(url), str(text)) for url, text in content.items() if text]
    if isinstance(content, str):
        return [("", content)] if content.strip() else []
    return [("", str(content))] if content else []


def _format_sources(docs: list[tuple[str, str]]) -> str:
    """Render documents as a source-attributed block for the prompt."""
    parts = []
    for source, text in docs:
        parts.append(f"[Source: {source}]\n{text}" if source else text)
    return "\n\n".join(parts)


def batch_documents(docs: list[tuple[str, str]], batch_chars: int) -> list[str]:
    """Pack documents into formatted batches no larger than *batch_chars*.

    A single document bigger than the budget is hard-split across consecutive
    batches so no content is ever dropped.
    """
    batches: list[str] = []
    current: list[tuple[str, str]] = []
    size = 0
    for source, text in docs:
        text = text or ""
        # Hard-split an oversized single document.
        while len(text) > batch_chars:
            if current:
                batches.append(_format_sources(current))
                current, size = [], 0
            batches.append(_format_sources([(source, text[:batch_chars])]))
            text = text[batch_chars:]
        if size + len(text) > batch_chars and current:
            batches.append(_format_sources(current))
            current, size = [], 0
        current.append((source, text))
        size += len(text)
    if current:
        batches.append(_format_sources(current))
    return batches


# ─────────────────────────────────────────────────────────────────────────────
# Prompt resolution (mirrors llm.generate_summary so output is unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_system_prompt(preset, custom_instructions, system_prompt_override) -> str:
    if system_prompt_override and system_prompt_override.strip():
        system_prompt = system_prompt_override
    else:
        system_prompt = PRESET_PROMPTS.get(preset, PRESET_PROMPTS["threat_intel"])
    if custom_instructions and custom_instructions.strip():
        system_prompt = system_prompt.rstrip() + f"\n\nAdditionally focus on: {custom_instructions.strip()}"
    return system_prompt


def _make_default_call(llm):
    """Default LLM invoker: build the prompt chain and call with retries."""
    def call(system_prompt: str, query: str, content: str) -> str:
        template = ChatPromptTemplate([("system", system_prompt), ("user", "{content}")])
        chain = template | llm | StrOutputParser()
        return _invoke_with_retry(chain, {"query": query, "content": content}, stage="summarize")
    return call


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_summary(
    llm,
    query,
    content,
    preset: str = "threat_intel",
    custom_instructions: str = "",
    system_prompt_override: str | None = None,
    *,
    batch_chars: int = DEFAULT_BATCH_CHARS,
    llm_call=None,
):
    """Summarize *content* into a report, processing all of it via map-reduce.

    Signature is drop-in compatible with :func:`llm.generate_summary` (the
    pipeline injects this as its ``summarize`` collaborator), plus keyword-only
    tuning knobs. ``llm_call`` is injected in tests.
    """
    call = llm_call or _make_default_call(llm)
    final_system = _resolve_system_prompt(preset, custom_instructions, system_prompt_override)

    docs = _normalize_content(content)
    batches = batch_documents(docs, batch_chars)

    # Small enough for one pass → single call (same cost/shape as before).
    if len(batches) <= 1:
        return call(final_system, query, batches[0] if batches else "")

    _logger.info("[Summarizer] map-reduce over %d batches (budget=%d chars).",
                 len(batches), batch_chars)

    # MAP: extract notes from every batch so all content reaches the model.
    notes = [call(MAP_SYSTEM_PROMPT, query, batch) for batch in batches]
    combined = _join_notes(notes)

    # If the notes still overflow, reduce them hierarchically before the final pass.
    guard = 0
    while len(combined) > batch_chars and len(notes) > 1 and guard < 3:
        guard += 1
        note_batches = batch_documents([("notes", combined)], batch_chars)
        notes = [call(MAP_SYSTEM_PROMPT, query, b) for b in note_batches]
        combined = _join_notes(notes)

    # REDUCE: synthesize the consolidated notes into the final domain report.
    return call(final_system, query, combined)


def _join_notes(notes: list[str]) -> str:
    return "\n\n".join(f"### Notes (batch {i + 1})\n{n}" for i, n in enumerate(notes))
