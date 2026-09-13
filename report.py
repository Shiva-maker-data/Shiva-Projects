"""
Builds the HTML email report from the day's TradeIdea picks -- v2 format,
matching the professional layout: signal + grade + confidence (separate
from score), full score breakdown, market regime, sector/relative
strength, structure-derived entry (or ENTRY MISSED), position sizing, and
an explicit invalidation statement.
"""
from __future__ import annotations

from datetime import datetime

from analyzer import ENTRY_MISSED, TradeIdea
import position_sizing as sizing
from positions import ClosedPosition

EXIT_LABELS = {
    "target1": ("Target hit", "#15803d"),
    "stop_loss": ("Stopped out", "#b91c1c"),
    "time_exit": ("Timed out", "#6b7280"),
}

SIGNAL_COLORS = {
    "STRONG BUY": "#15803d",
    "BUY": "#1d4ed8",
    "WATCH": "#b45309",
    "NO TRADE": "#6b7280",
}

DISCLAIMER = (
    "This email is generated automatically by a personal, rule-based technical + regime/sector "
    "screening script. It is NOT investment advice from a SEBI-registered analyst/advisor, and is "
    "for personal, educational/informational use only. Score reflects how many weighted rule-based "
    "conditions line up; Confidence reflects how much of the available evidence agrees and how "
    "complete the day's data was -- NEITHER is a calibrated probability of profit unless explicitly "
    "stated as such after real out-of-sample validation (see README for the actual measured backtest "
    "numbers, including where no edge was found). This tool only covers long entries in NSE cash-segment "
    "equities -- there is no short-selling signal. Equity markets carry risk of loss. Always respect "
    "the stated stop-loss, size positions sensibly, and do your own due diligence (or consult a "
    "registered investment advisor) before placing any trade."
)

CATEGORY_COLORS = {
    "Intraday": "#b45309",
    "Short-Term (Swing)": "#1d4ed8",
    "Long-Term": "#15803d",
}

REGIME_COLORS = {
    "STRONG_BULLISH": "#15803d", "BULLISH": "#22c55e", "NEUTRAL": "#6b7280",
    "BEARISH": "#f97316", "STRONG_BEARISH": "#b91c1c", "HIGH_VOLATILITY": "#a855f7",
}


def _score_breakdown_table(breakdown: dict) -> str:
    rows = "".join(
        f'<tr><td style="padding:2px 10px 2px 0;color:#4b5563;">{name}</td>'
        f'<td style="padding:2px 0;font-weight:600;text-align:right;">{earned:.1f}/{maxpts:.0f}</td></tr>'
        for name, (earned, maxpts) in breakdown.items()
        if maxpts > 0  # e.g. Intraday doesn't score Risk/Reward as its own weighted factor
    )
    return f'<table style="font-size:12px;border-collapse:collapse;margin-top:6px;">{rows}</table>'


def _is_caution_reason(r: str) -> bool:
    """Reasons that read as a warning/caveat rather than an affirmative
    signal -- these go in Risk Flags (or are already in the header summary
    line), never as a ✅ bullet under "why this trade"."""
    markers = ("CONFLICT", "below the", "Underperforming", "underperforming", "Caution",
               "Price has moved", "conflict", "excessively", "unavailable", "not evaluated")
    return any(m in r for m in markers)


def _why_this_trade(reasons: list[str]) -> str:
    # Regime/sector restatements are already shown in the card's header
    # summary line -- repeating them here as a green checkmark would be
    # misleading when the regime/sector is actually unfavorable.
    skip_prefixes = ("Market regime", "Sector index", "No reliable free sector-index")
    items = "".join(
        f'<div style="margin:3px 0;">✅ {r}</div>' for r in reasons
        if not r.startswith(skip_prefixes) and not _is_caution_reason(r)
    )
    return items


def _risk_flags(idea: TradeIdea) -> str:
    flags = [r for r in idea.reasons if _is_caution_reason(r) and not r.startswith("Sector index")]
    if not flags:
        return ""
    items = "".join(f'<div style="margin:3px 0;color:#b45309;">⚠️ {f}</div>' for f in flags)
    return f'<div style="margin-top:8px;">{items}</div>'


def _idea_row(idea: TradeIdea, rationale: str) -> str:
    color = CATEGORY_COLORS.get(idea.category, "#374151")
    signal_color = SIGNAL_COLORS.get(idea.signal, "#6b7280")
    grade_str = idea.grade or "--"

    entry_html = (
        f'<span style="color:#b45309;font-weight:700;">{ENTRY_MISSED}</span> '
        f'<span style="color:#6b7280;">(ideal zone was Rs {idea.entry_low} - {idea.entry_high})</span>'
        if idea.chase_flag else
        f'Rs {idea.entry_low} - {idea.entry_high} <span style="color:#6b7280;font-weight:400;">({idea.entry_type})</span>'
    )

    pos = sizing.calculate_position_size(idea.last_price, idea.stop_loss, grade_str)
    sizing_html = (
        f'{pos.shares} shares (~Rs {pos.capital_deployed:,.0f} deployed, Rs {pos.capital_at_risk:,.0f} at risk) '
        f'<span style="color:#6b7280;">-- based on Rs {pos.account_capital:,.0f} capital @ {pos.risk_per_trade_pct:.1f}% risk/trade</span>'
        if pos.shares > 0 else
        f'<span style="color:#6b7280;">{pos.note}</span>'
    )

    rs_html = f"{idea.relative_strength_pct:+.1f}pp vs NIFTY" if idea.relative_strength_pct is not None else "n/a"
    note = f'<div style="font-size:12px;color:#b45309;margin-top:6px;">⚠ Data check: {idea.data_note}</div>' if "differ" in idea.data_note else ""

    return f"""
    <tr>
      <td style="padding:16px;border-bottom:1px solid #e5e7eb;">
        <div style="font-size:16px;font-weight:700;color:#111827;">
          {idea.symbol}
          <span style="font-size:11px;font-weight:700;color:#fff;background:{signal_color};border-radius:4px;padding:3px 8px;margin-left:6px;">{idea.signal}</span>
          <span style="font-size:11px;font-weight:600;color:#374151;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:4px;padding:2px 6px;margin-left:4px;">Grade {grade_str}</span>
        </div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px;">
          Score {idea.score}/100 &nbsp;|&nbsp; Confidence {idea.confidence:.0f}/100 &nbsp;|&nbsp;
          Regime: {idea.market_regime_label} &nbsp;|&nbsp; Sector: {idea.sector_trend} &nbsp;|&nbsp; RS: {rs_html}
        </div>
        <div style="font-size:13px;color:#4b5563;margin-top:8px;line-height:1.5;">{rationale}</div>

        <div style="margin-top:10px;font-size:13px;">
          <div><strong>Entry zone:</strong> {entry_html}</div>
          <div style="margin-top:4px;"><strong>Target 1:</strong> Rs {idea.target1} (+{idea.target1_pct}%) &nbsp;
              <strong>Target 2:</strong> Rs {idea.target2} (+{idea.target2_pct}%)</div>
          <div style="margin-top:4px;"><strong>Stop-loss:</strong> <span style="color:#b91c1c;">Rs {idea.stop_loss} ({idea.stop_loss_pct}%)</span> &nbsp;
              <strong>R:R</strong> {idea.rr_ratio}:1 &nbsp; <strong>Horizon:</strong> {idea.horizon}</div>
          <div style="margin-top:4px;"><strong>Position size:</strong> {sizing_html}</div>
        </div>

        <details style="margin-top:8px;">
          <summary style="font-size:12px;color:#374151;cursor:pointer;">Score breakdown</summary>
          {_score_breakdown_table(idea.score_breakdown)}
        </details>

        <div style="margin-top:8px;font-size:13px;">{_why_this_trade(idea.reasons)}</div>
        {_risk_flags(idea)}

        <div style="margin-top:8px;font-size:12px;color:#6b7280;">
          <strong>Invalidation:</strong> thesis is invalid if price closes below Rs {idea.stop_loss}.
        </div>
        {note}
      </td>
    </tr>
    """


def _category_section(title: str, ideas: list[TradeIdea], rationales: dict[str, str]) -> str:
    if not ideas:
        return f"""
        <h2 style="font-size:15px;color:#111827;margin:24px 0 8px 0;border-left:4px solid #9ca3af;padding-left:10px;">{title}</h2>
        <p style="font-size:13px;color:#6b7280;padding-left:10px;">No new candidate today -- either nothing cleared the minimum score, every qualifying idea is already an open pick from a previous day, or every candidate resolved to NO TRADE (poor R:R, hostile market regime, or an entry already missed). No trade is a valid outcome.</p>
        """
    rows = "".join(_idea_row(idea, rationales.get(idea.symbol + idea.category, "")) for idea in ideas)
    border_color = CATEGORY_COLORS.get(title, "#9ca3af")
    return f"""
    <h2 style="font-size:15px;color:#111827;margin:24px 0 8px 0;border-left:4px solid {border_color};padding-left:10px;">{title}</h2>
    <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
      {rows}
    </table>
    """


def _position_updates_section(closed: list[ClosedPosition]) -> str:
    if not closed:
        return ""
    rows = []
    for p in closed:
        label, color = EXIT_LABELS.get(p.exit_reason, (p.exit_reason, "#6b7280"))
        sign = "+" if p.return_pct >= 0 else ""
        rows.append(f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #e5e7eb;font-size:13px;">
            <strong>{p.symbol}</strong> <span style="color:#6b7280;">[{p.category}]</span>
            &nbsp;-- first flagged {p.first_shown_date}, resolved {p.closed_date}
          </td>
          <td style="padding:10px 16px;border-bottom:1px solid #e5e7eb;font-size:13px;text-align:right;white-space:nowrap;">
            <span style="font-size:11px;font-weight:600;color:#fff;background:{color};border-radius:4px;padding:2px 6px;">{label}</span>
            <strong style="margin-left:6px;color:{color};">{sign}{p.return_pct}%</strong>
          </td>
        </tr>
        """)
    return f"""
    <h2 style="font-size:15px;color:#111827;margin:0 0 8px 0;border-left:4px solid #111827;padding-left:10px;">Position Updates -- What Happened To Earlier Picks</h2>
    <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;margin-bottom:8px;">
      {"".join(rows)}
    </table>
    """


def _market_snapshot(picks_by_category: dict[str, list[TradeIdea]]) -> str:
    all_ideas = [i for ideas in picks_by_category.values() for i in ideas]
    if not all_ideas:
        return ""
    label = all_ideas[0].market_regime_label
    color = REGIME_COLORS.get(label, "#6b7280")
    return f"""
    <div style="margin-bottom:16px;padding:10px 14px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;font-size:13px;">
      <strong>Market Regime (NIFTY 50):</strong>
      <span style="font-size:11px;font-weight:700;color:#fff;background:{color};border-radius:4px;padding:2px 8px;margin-left:4px;">{label}</span>
      <span style="color:#6b7280;"> -- every score below already accounts for this; a hostile regime caps how high any stock can score.</span>
    </div>
    """


def _nse_cross_check_note(picks_by_category: dict[str, list[TradeIdea]]) -> str:
    all_ideas = [i for ideas in picks_by_category.values() for i in ideas]
    if not all_ideas:
        return ""
    unavailable = sum(1 for i in all_ideas if "NSE quote unavailable" in i.data_note)
    if unavailable == len(all_ideas):
        text = ("NSE India's cross-check API was unavailable for today's run (it blocks "
                "essentially all automated requests) -- all analysis below is based on "
                "Yahoo Finance data only, same as always; nothing was computed from NSE's "
                "price, so this doesn't affect the picks themselves.")
    elif unavailable == 0:
        text = "NSE India's cross-check agreed with Yahoo Finance for every pick below."
    else:
        text = (f"NSE India's cross-check was unavailable for {unavailable} of {len(all_ideas)} "
                f"pick(s) today; the rest agreed with Yahoo Finance.")
    return f'<p style="font-size:11px;color:#9ca3af;margin:0 0 16px 0;">{text}</p>'


def build_html_report(picks_by_category: dict[str, list[TradeIdea]], rationales: dict[str, str],
                       run_date: datetime | None = None, skipped_symbols: list[str] | None = None,
                       closed_positions: list[ClosedPosition] | None = None) -> str:
    run_date = run_date or datetime.now()
    date_str = run_date.strftime("%A, %d %B %Y")

    market_snapshot = _market_snapshot(picks_by_category)
    updates_section = _position_updates_section(closed_positions or [])
    cross_check_note = _nse_cross_check_note(picks_by_category)
    sections = "".join(
        _category_section(category, picks_by_category.get(category, []), rationales)
        for category in ["Intraday", "Short-Term (Swing)", "Long-Term"]
    )

    skipped_note = ""
    if skipped_symbols:
        skipped_note = (
            f'<p style="font-size:11px;color:#9ca3af;margin-top:20px;">'
            f"Skipped {len(skipped_symbols)} symbol(s) due to data fetch issues today: "
            f'{", ".join(skipped_symbols)}</p>'
        )

    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;max-width:680px;margin:0 auto;background:#f9fafb;padding:20px;">
      <div style="background:#111827;border-radius:10px 10px 0 0;padding:20px 24px;">
        <div style="color:#fff;font-size:20px;font-weight:700;">NIFTY 50 / SENSEX -- Daily Watchlist</div>
        <div style="color:#9ca3af;font-size:13px;margin-top:4px;">{date_str}</div>
      </div>
      <div style="background:#fff;padding:20px 24px;border:1px solid #e5e7eb;border-top:none;">
        {market_snapshot}
        {cross_check_note}
        {updates_section}
        {sections}
        {skipped_note}
      </div>
      <div style="background:#f3f4f6;border-radius:0 0 10px 10px;padding:16px 24px;border:1px solid #e5e7eb;border-top:none;">
        <p style="font-size:11px;color:#6b7280;line-height:1.6;margin:0;">{DISCLAIMER}</p>
      </div>
    </div>
    """
