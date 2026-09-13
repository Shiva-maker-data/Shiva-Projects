"""
Builds the HTML email report from the day's TradeIdea picks.
"""
from __future__ import annotations

from datetime import datetime

from analyzer import TradeIdea
from positions import ClosedPosition

EXIT_LABELS = {
    "target1": ("Target hit", "#15803d"),
    "stop_loss": ("Stopped out", "#b91c1c"),
    "time_exit": ("Timed out", "#6b7280"),
}

DISCLAIMER = (
    "This email is generated automatically by a personal, rule-based technical-analysis script. "
    "It is NOT investment advice from a SEBI-registered analyst/advisor, and is for personal, "
    "educational/informational use only. Technical scores reflect how many textbook bullish "
    "conditions currently line up -- they are not a prediction or guarantee of profit. Equity "
    "markets carry risk of loss, including intraday leverage risk. Always size positions "
    "sensibly, respect the stated stop-loss, and do your own due diligence (or consult a "
    "registered investment advisor) before placing any trade."
)

CATEGORY_COLORS = {
    "Intraday": "#b45309",
    "Short-Term (Swing)": "#1d4ed8",
    "Long-Term": "#15803d",
}


def _idea_row(idea: TradeIdea, rationale: str) -> str:
    color = CATEGORY_COLORS.get(idea.category, "#374151")
    # Only surface the per-stock data-check note when it's an actual price
    # discrepancy worth knowing about -- NSE's cross-check API is blocked
    # for essentially all automated requests (see the one-line summary
    # footnote instead), so repeating "NSE unavailable" on every single
    # pick, every single day, is just noise with zero new information.
    note = (
        f'<div style="font-size:12px;color:#b45309;margin-top:6px;">⚠ Data check: {idea.data_note}</div>'
        if "differ" in idea.data_note else ""
    )
    return f"""
    <tr>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;">
        <div style="font-size:16px;font-weight:700;color:#111827;">{idea.symbol}
          <span style="font-size:11px;font-weight:600;color:#fff;background:{color};border-radius:4px;padding:2px 6px;margin-left:6px;">
            Score {idea.score}/100
          </span>
        </div>
        <div style="font-size:13px;color:#4b5563;margin-top:6px;line-height:1.5;">{rationale}</div>
        <table style="margin-top:10px;font-size:13px;border-collapse:collapse;">
          <tr>
            <td style="padding:2px 12px 2px 0;color:#6b7280;">Last price</td>
            <td style="padding:2px 0;font-weight:600;">Rs {idea.last_price}</td>
            <td style="padding:2px 12px 2px 20px;color:#6b7280;">Entry zone</td>
            <td style="padding:2px 0;font-weight:600;">Rs {idea.entry_low} - {idea.entry_high}</td>
          </tr>
          <tr>
            <td style="padding:2px 12px 2px 0;color:#6b7280;">Target 1</td>
            <td style="padding:2px 0;font-weight:600;color:#15803d;">Rs {idea.target1} <span style="font-weight:700;">(+{idea.target1_pct}%)</span></td>
            <td style="padding:2px 12px 2px 20px;color:#6b7280;">Target 2 (stretch)</td>
            <td style="padding:2px 0;font-weight:600;color:#15803d;">Rs {idea.target2} <span style="font-weight:700;">(+{idea.target2_pct}%)</span></td>
          </tr>
          <tr>
            <td style="padding:2px 12px 2px 0;color:#6b7280;">Stop-loss</td>
            <td style="padding:2px 0;font-weight:600;color:#b91c1c;">Rs {idea.stop_loss} <span style="font-weight:700;">({idea.stop_loss_pct}%)</span></td>
            <td style="padding:2px 12px 2px 20px;color:#6b7280;">Reward:Risk</td>
            <td style="padding:2px 0;font-weight:600;">{idea.rr_ratio}:1</td>
          </tr>
          <tr>
            <td style="padding:2px 12px 2px 0;color:#6b7280;">Horizon</td>
            <td colspan="3" style="padding:2px 0;font-weight:600;">{idea.horizon}</td>
          </tr>
        </table>
        {note}
      </td>
    </tr>
    """


def _category_section(title: str, ideas: list[TradeIdea], rationales: dict[str, str]) -> str:
    if not ideas:
        return f"""
        <h2 style="font-size:15px;color:#111827;margin:24px 0 8px 0;border-left:4px solid #9ca3af;padding-left:10px;">{title}</h2>
        <p style="font-size:13px;color:#6b7280;padding-left:10px;">No new candidate today -- either nothing cleared the minimum score, or every qualifying idea is already an open pick from a previous day (see Position Updates above once it resolves). No trade is a valid outcome.</p>
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


def _nse_cross_check_note(picks_by_category: dict[str, list[TradeIdea]]) -> str:
    """One aggregate line on whether today's NSE secondary-source check was
    available, instead of repeating the same boilerplate on every pick.
    NSE's own price was never used in any score/target/stop-loss
    calculation -- everything is computed from Yahoo Finance OHLCV data
    regardless of whether this cross-check succeeds."""
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
