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

from analyzer import ENTRY_MISSED, TradeIdea

logger = logging.getLogger("nifty_agent.narrative")
ENTRY_MISSED_TEXT = f"{ENTRY_MISSED} (price has already run past the ideal zone)"

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
    entry_text = ENTRY_MISSED_TEXT if idea.chase_flag else f"Suggested entry {idea.entry_low}-{idea.entry_high} ({idea.entry_type})"
    return (
        f"[{idea.signal}, Grade {idea.grade or 'below C'}] {reason_text} {entry_text}, "
        f"target {idea.target1} (+{idea.target1_pct}%) (stretch {idea.target2}, +{idea.target2_pct}%), "
        f"stop-loss {idea.stop_loss} ({idea.stop_loss_pct}%) "
        f"(reward:risk to target1 = {idea.rr_ratio}:1). Horizon: {idea.horizon}. "
        f"Confidence {idea.confidence:.0f}/100 (evidence agreement, not a win-probability)."
    )


def write_rationale(idea: TradeIdea) -> str:
    client = _get_client()
    if client is None:
        return _template_narrative(idea)

    signal_lines = "\n".join(f"- {r}" for r in idea.reasons) or "- No strong individual signals; mixed picture."
    rs_line = f"{idea.relative_strength_pct:+.1f} percentage points vs NIFTY" if idea.relative_strength_pct is not None else "not available"
    prompt = f"""You are an experienced Indian equity market analyst writing a short note for a client's daily watchlist email.
The DETERMINISTIC RULE ENGINE below has already made every decision (score, grade, signal, entry/target/stop-loss).
Your job is ONLY to explain that decision in plain language -- you must NOT invent a different signal, upgrade/downgrade
the conviction, mention news/earnings/events not listed here, or imply a win-probability. If the engine says WATCH or
NO TRADE, your tone must reflect that caution, not talk it up into a buy.

Stock: {idea.symbol} (NSE)
Category: {idea.category}
Signal: {idea.signal}   Grade: {idea.grade or "below C (NO TRADE)"}
Score: {idea.score}/100   Confidence: {idea.confidence:.0f}/100 (these are DIFFERENT things -- score is how many rules matched, confidence is how much the evidence agrees)
Market regime: {idea.market_regime_label}   Sector trend: {idea.sector_trend}   Relative strength vs NIFTY: {rs_line}
Last price: Rs {idea.last_price}
Entry: {"ENTRY MISSED -- price has run too far, do not chase" if idea.chase_flag else f"Rs {idea.entry_low} - {idea.entry_high} ({idea.entry_type})"}
Target 1: Rs {idea.target1} (+{idea.target1_pct}%)
Target 2 (stretch): Rs {idea.target2} (+{idea.target2_pct}%)
Stop-loss: Rs {idea.stop_loss} ({idea.stop_loss_pct}%)
Reward:risk to target 1: {idea.rr_ratio}:1
Holding horizon: {idea.horizon}

Score breakdown by factor (this is ALL the information you have -- do not invent news, earnings, sector events, or
any fact not listed here):
{signal_lines}

Write a 2-3 sentence rationale in a confident but measured expert-broker tone, explaining WHY this combination of
factors produced this signal and grade, and HOW the trader should approach it. Do not mention specific news, results,
or events. Do not state or imply a win-probability or accuracy percentage. Plain text only, no markdown."""

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
