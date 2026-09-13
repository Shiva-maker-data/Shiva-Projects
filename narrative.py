"""
Turns a structured TradeIdea into a short, expert-broker-style written
rationale.

If ANTHROPIC_API_KEY is set in the environment, uses Claude to write a
polished 2-4 sentence summary -- but the prompt explicitly restricts it to
the numeric signals we computed ourselves, so it explains the *quant*
rationale in plain English rather than inventing news, catalysts, or facts
that weren't given to it. If no API key is set (or the call fails for any
reason), falls back to a deterministic template built from the same
reasons list -- the email always works, LLM or not.
"""
from __future__ import annotations

import logging
import os

from analyzer import TradeIdea

logger = logging.getLogger("nifty_agent.narrative")

_client = None
_client_checked = False


def _get_client():
    """Lazily construct an Anthropic client if a key is configured."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.info("Anthropic client unavailable, using template narratives: %s", exc)
        _client = None
    return _client


def _template_narrative(idea: TradeIdea) -> str:
    reason_text = " ".join(idea.reasons) if idea.reasons else "Signals are mixed; treat as a lower-conviction idea."
    return (
        f"{reason_text} Suggested entry {idea.entry_low}-{idea.entry_high}, "
        f"target {idea.target1} (+{idea.target1_pct}%) (stretch {idea.target2}, +{idea.target2_pct}%), "
        f"stop-loss {idea.stop_loss} ({idea.stop_loss_pct}%) "
        f"(reward:risk to target1 = {idea.rr_ratio}:1). Horizon: {idea.horizon}."
    )


def write_rationale(idea: TradeIdea) -> str:
    client = _get_client()
    if client is None:
        return _template_narrative(idea)

    signal_lines = "\n".join(f"- {r}" for r in idea.reasons) or "- No strong individual signals; mixed picture."
    prompt = f"""You are an experienced Indian equity market analyst writing a short note for a client's daily watchlist email.

Stock: {idea.symbol} (NSE)
Category: {idea.category}
Score (0-100, our internal technical score): {idea.score}
Last price: Rs {idea.last_price}
Suggested entry zone: Rs {idea.entry_low} - {idea.entry_high}
Target 1: Rs {idea.target1} (+{idea.target1_pct}%)
Target 2 (stretch): Rs {idea.target2} (+{idea.target2_pct}%)
Stop-loss: Rs {idea.stop_loss} ({idea.stop_loss_pct}%)
Reward:risk to target 1: {idea.rr_ratio}:1
Holding horizon: {idea.horizon}

Technical signals detected (this is ALL the information you have -- do not invent news, earnings, sector events, or any fact not listed here):
{signal_lines}

Write a 2-3 sentence rationale in a confident but measured expert-broker tone, explaining WHY these technical signals support this idea and HOW the trader should approach it (entry, target, stop-loss). Do not mention specific news, results, or events. Do not guarantee any outcome. Plain text only, no markdown."""

    try:
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text")).strip()
        return text if text else _template_narrative(idea)
    except Exception as exc:  # noqa: BLE001
        logger.info("Claude narrative generation failed for %s, using template: %s", idea.symbol, exc)
        return _template_narrative(idea)
