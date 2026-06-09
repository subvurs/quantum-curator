"""Separate SMTP path for Quantum Intel daily reports (decision D6).

Curator already has an email_report.py that ships the daily Quantum
Crier post round-up. Intel content (today's new entries, generated
concept briefs, the structured daily summary) is a different audience
purpose — it goes into a separate message body, sent over the same
Gmail credentials (``settings.smtp_email`` / ``settings.smtp_app_password``).

This is the "both Curator and Intel emails get full content" half of
decision D6: Intel keeps its own send so a Curator-email failure can't
take Intel content offline (and vice versa).

The HTML aesthetic mirrors the legacy Intel emailer.py (dark theme,
indigo / cyan / emerald accent strip) so the email reads familiar to
Mark. We do not port the scaffolds / review / partial-banner sections
— SCAFFOLD and REVIEW were dropped in decisions D7 / D8.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import inventory_view


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
# Per Intel's emailer (Jun 7 2026 5h25m hang root-cause): smtplib
# defaults to socket._GLOBAL_DEFAULT_TIMEOUT (= None), so a stalled
# Gmail send blocks forever. 30 s wall-clock cap on both the SMTP
# socket and the underlying socket.
SMTP_TIMEOUT_SEC = 30


def _summary_html_block(summary: dict | None) -> str:
    """Render the structured daily summary at the top of the email."""
    if not summary:
        return (
            '<div style="margin: 16px 0; padding: 14px; background: #1e293b; '
            'border-left: 3px solid #64748b; border-radius: 4px; color: #94a3b8;">'
            "AI summary unavailable for today's run."
            "</div>"
        )

    def _ul(items: list[Any], color: str) -> str:
        if not items:
            return ""
        rows = "".join(
            f'<li style="color: #cbd5e1; font-size: 13px; margin: 4px 0;">{str(it)}</li>'
            for it in items
        )
        return (
            f'<ul style="margin: 4px 0 12px 18px; padding: 0; '
            f'border-left: 2px solid {color};">{rows}</ul>'
        )

    win = summary.get("window") or {}
    tags = summary.get("tags") or []
    tag_html = " ".join(
        f'<span style="display:inline-block; padding:2px 8px; margin:2px; '
        f'background:#334155; color:#94a3b8; border-radius:4px; font-size:11px;">'
        f"{t}</span>"
        for t in tags
    )
    return (
        '<div style="margin: 16px 0; padding: 18px; background: #1e293b; '
        'border-left: 3px solid #6366f1; border-radius: 6px;">'
        '<h2 style="color: #818cf8; margin: 0 0 10px; font-size: 16px;">Daily Summary</h2>'
        f'<div style="color: #94a3b8; font-size: 12px; margin-bottom: 6px;">'
        f"window: {win.get('n_today', 0)} new, {win.get('n_prior', 0)} prior &nbsp;·&nbsp; {tag_html}"
        f"</div>"
        '<h3 style="color: #6366f1; font-size: 13px; margin: 10px 0 4px;">TL;DR</h3>'
        + _ul(summary.get("tldr", []), "#6366f1")
        + '<h3 style="color: #06b6d4; font-size: 13px; margin: 10px 0 4px;">Implications vs Prior 7d</h3>'
        + _ul(summary.get("implications", []), "#06b6d4")
        + '<h3 style="color: #10b981; font-size: 13px; margin: 10px 0 4px;">Worth Attention</h3>'
        + _ul(summary.get("attention", []), "#10b981")
        + "</div>"
    )


def _entries_table(new_entries: list[dict]) -> str:
    if not new_entries:
        return (
            '<div style="margin: 16px 0; padding: 16px; background: #1e293b; '
            'border-radius: 8px; text-align: center; color: #94a3b8;">'
            "No new entries cataloged today (all deduplicated)."
            "</div>"
        )
    rows = ""
    for e in new_entries[:50]:  # cap at 50 for inbox sanity
        title = (e.get("title") or e.get("summary") or "untitled")[:120]
        summary = (e.get("summary") or "")[:160]
        tags = ", ".join(e.get("domain_tags") or [])
        maturity = e.get("maturity") or "?"
        url = e.get("url") or ""
        score = e.get("subvurs_impact_score")
        score_html = (
            f'<span style="color:#a5b4fc; font-size:11px; margin-left:6px;">'
            f"impact: {score:.2f}</span>"
            if isinstance(score, (int, float)) and score > 0
            else ""
        )
        rows += (
            "<tr>"
            '<td style="padding: 8px 10px; border-bottom: 1px solid #334155; vertical-align: top;">'
            f'<a href="{url}" style="color: #818cf8; text-decoration: none; '
            f'font-weight: 600; font-size: 13px;">{title}</a>{score_html}'
            f'<br><span style="color: #94a3b8; font-size: 12px;">{summary}</span>'
            "</td>"
            f'<td style="padding: 8px 10px; border-bottom: 1px solid #334155; '
            f'color: #06b6d4; font-size: 12px; white-space: nowrap; vertical-align: top;">{tags}</td>'
            f'<td style="padding: 8px 10px; border-bottom: 1px solid #334155; '
            f'color: #94a3b8; font-size: 12px; vertical-align: top;">{maturity}</td>'
            "</tr>"
        )
    return (
        '<div style="margin-top: 20px;">'
        f'<h2 style="color: #6366f1; font-size: 16px; margin-bottom: 10px;">'
        f"New Entries ({len(new_entries)})</h2>"
        '<table style="width: 100%; border-collapse: collapse;"><thead><tr>'
        '<th style="text-align: left; padding: 8px 10px; color: #94a3b8; '
        'border-bottom: 2px solid #334155;">Article</th>'
        '<th style="text-align: left; padding: 8px 10px; color: #94a3b8; '
        'border-bottom: 2px solid #334155;">Tags</th>'
        '<th style="text-align: left; padding: 8px 10px; color: #94a3b8; '
        'border-bottom: 2px solid #334155;">Maturity</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _briefs_section(briefs: list[Path]) -> str:
    if not briefs:
        return ""
    items = ""
    for bp in briefs:
        try:
            content = bp.read_text()
        except OSError:
            continue
        first_line = content.split("\n", 1)[0]
        name = first_line.replace("# ", "").strip() or bp.stem
        conf_line = next((l for l in content.split("\n") if "Confidence" in l), "")
        conf = conf_line.split(":")[-1].strip() if conf_line else "?"
        body_preview = content[:1500]
        items += (
            '<div style="margin: 10px 0; padding: 14px; background: #1e293b; '
            'border-left: 3px solid #6366f1; border-radius: 4px;">'
            f'<span style="color: #6366f1; font-weight: 700; font-size: 15px;">{name}</span>'
            f'<span style="float: right; color: #06b6d4; font-size: 13px;">Confidence: {conf}</span>'
            f'<pre style="margin: 8px 0 0; color: #cbd5e1; font-size: 12px; '
            f'white-space: pre-wrap; font-family: inherit;">{body_preview}</pre>'
            "</div>"
        )
    return (
        '<div style="margin-top: 24px;">'
        '<h2 style="color: #6366f1; font-size: 16px; margin-bottom: 8px;">'
        "Concept Briefs Generated</h2>"
        f"{items}</div>"
    )


def build_html(
    *,
    new_entries: list[dict],
    briefs: list[Path],
    summary: dict | None,
    inventory_total: int,
    elapsed_seconds: float | None = None,
) -> str:
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    n_entries = len(new_entries)
    n_briefs = len(briefs)
    elapsed_html = (
        f'<div><span style="color: #94a3b8; font-size: 24px; font-weight: 700;">'
        f'{int(elapsed_seconds)}s</span>'
        f'<br><span style="color: #94a3b8; font-size: 12px;">Runtime</span></div>'
        if elapsed_seconds is not None
        else ""
    )
    return (
        "<!DOCTYPE html>\n<html>\n"
        '<head><meta charset="utf-8"></head>\n'
        '<body style="background-color: #0f172a; color: #e2e8f0; '
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        'margin: 0; padding: 20px;">\n'
        '<div style="max-width: 800px; margin: 0 auto;">\n'
        '<div style="text-align: center; padding: 20px 0; border-bottom: 2px solid #6366f1;">\n'
        '<h1 style="color: #6366f1; margin: 0; font-size: 22px;">Quantum Intel</h1>\n'
        f'<p style="color: #94a3b8; margin: 8px 0 0;">{today_str}</p>\n'
        "</div>\n"
        '<div style="display: flex; justify-content: space-around; padding: 16px 0; '
        'border-bottom: 1px solid #334155; text-align: center;">'
        f'<div><span style="color: #6366f1; font-size: 24px; font-weight: 700;">{n_entries}</span>'
        '<br><span style="color: #94a3b8; font-size: 12px;">New Entries</span></div>'
        f'<div><span style="color: #a5b4fc; font-size: 24px; font-weight: 700;">{inventory_total}</span>'
        '<br><span style="color: #94a3b8; font-size: 12px;">Total Inventory</span></div>'
        f'<div><span style="color: #6366f1; font-size: 24px; font-weight: 700;">{n_briefs}</span>'
        '<br><span style="color: #94a3b8; font-size: 12px;">Briefs</span></div>'
        f"{elapsed_html}"
        "</div>\n"
        + _summary_html_block(summary)
        + _entries_table(new_entries)
        + _briefs_section(briefs)
        + '<div style="margin-top: 30px; padding-top: 16px; border-top: 1px solid #334155; '
        'text-align: center; color: #475569; font-size: 12px;">'
        "Quantum Intel &middot; Daily report &middot; Subvurs Research"
        "</div>\n"
        "</div>\n</body>\n</html>"
    )


def send_intel_email(
    *,
    new_entries: list[dict] | None = None,
    briefs: list[Path] | None = None,
    summary: dict | None = None,
    elapsed_seconds: float | None = None,
    recipient: str | None = None,
) -> bool:
    """Send the Intel daily email. Returns True on success.

    All args are optional — defaults pull today's entries from the DB
    and use Curator's configured Gmail credentials. Caller supplies
    briefs / summary / elapsed when running as part of a full pipeline.
    """
    settings = get_settings()
    if not settings.has_email:
        print("[intel.emailer] smtp_email / smtp_app_password not configured")
        return False

    new_entries = new_entries if new_entries is not None else inventory_view.today_entries(days=1)
    briefs = briefs or []
    inventory_total = len(inventory_view.load_inventory())
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    html = build_html(
        new_entries=new_entries,
        briefs=briefs,
        summary=summary,
        inventory_total=inventory_total,
        elapsed_seconds=elapsed_seconds,
    )

    subject = (
        f"Quantum Intel: {len(new_entries)} new entries, "
        f"{len(briefs)} briefs — {today_str}"
    )
    recipient = recipient or settings.smtp_email

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_email
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SEC) as server:
            server.sock.settimeout(SMTP_TIMEOUT_SEC)
            server.login(settings.smtp_email, settings.smtp_app_password)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 — surface but don't crash the cron
        print(f"[intel.emailer] send failed: {exc}")
        return False
