"""Daily Subvurs insights email report for Quantum Curator."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import get_settings
from .db import list_curated_posts

logger = logging.getLogger(__name__)


def build_insights_report(days: int = 1) -> tuple[str, str, int]:
    """Build an HTML email report of Subvurs research connections.

    Args:
        days: Look back this many days for curated posts (default: 1).

    Returns:
        Tuple of (subject, html_body, connection_count).
    """
    since = datetime.utcnow() - timedelta(days=days)
    posts = list_curated_posts(since=since, limit=200)

    with_notes = [p for p in posts if p.subvurs_notes]
    today_str = datetime.utcnow().strftime("%B %d, %Y")

    subject = f"Quantum Curator: {len(with_notes)} Subvurs connections found — {today_str}"

    rows = ""
    for p in with_notes:
        date_str = p.published_at.strftime("%Y-%m-%d") if p.published_at else "N/A"
        rows += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #334155; vertical-align: top;">
                <a href="{p.original_url}" style="color: #818cf8; text-decoration: none; font-weight: 600;">{p.title}</a>
                <br><span style="color: #94a3b8; font-size: 13px;">{p.source_name} &middot; {date_str}</span>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #334155; color: #e2e8f0; vertical-align: top; font-size: 14px; line-height: 1.5;">
                {p.subvurs_notes}
            </td>
        </tr>"""

    no_connection_rows = ""
    without_notes = [p for p in posts if not p.subvurs_notes]
    for p in without_notes:
        no_connection_rows += f"""
        <tr>
            <td style="padding: 6px 12px; border-bottom: 1px solid #1e293b; color: #64748b; font-size: 13px;">
                {p.title[:80]}{'...' if len(p.title) > 80 else ''}
            </td>
            <td style="padding: 6px 12px; border-bottom: 1px solid #1e293b; color: #475569; font-size: 13px;">
                {p.source_name}
            </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background-color: #0f172a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px;">

<div style="max-width: 800px; margin: 0 auto;">

    <div style="text-align: center; padding: 20px 0; border-bottom: 2px solid #6366f1;">
        <h1 style="color: #6366f1; margin: 0; font-size: 24px;">Quantum Curator &mdash; Subvurs Insights</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0;">{today_str} &middot; {len(posts)} articles curated &middot; {len(with_notes)} connections found</p>
    </div>

    {"<div style='margin-top: 24px;'><h2 style=\"color: #818cf8; font-size: 18px; margin-bottom: 12px;\">Research Connections</h2><table style=\"width: 100%; border-collapse: collapse;\"><thead><tr><th style=\"text-align: left; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155; width: 35%;\">Article</th><th style=\"text-align: left; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155;\">Subvurs Connection</th></tr></thead><tbody>" + rows + "</tbody></table></div>" if with_notes else "<div style='margin-top: 24px; padding: 20px; background: #1e293b; border-radius: 8px; text-align: center; color: #94a3b8;'>No Subvurs research connections found in today's articles.</div>"}

    {"<div style='margin-top: 24px;'><h2 style=\"color: #64748b; font-size: 16px; margin-bottom: 8px;\">Other Articles Curated (no connections)</h2><table style=\"width: 100%; border-collapse: collapse;\"><tbody>" + no_connection_rows + "</tbody></table></div>" if without_notes else ""}

    <div style="margin-top: 30px; padding-top: 16px; border-top: 1px solid #334155; text-align: center; color: #475569; font-size: 12px;">
        Quantum Curator &middot; Automated daily report &middot; <a href="https://quantumcrier.com" style="color: #6366f1;">quantumcrier.com</a>
    </div>

</div>
</body>
</html>"""

    return subject, html, len(with_notes)


def send_insights_email(days: int = 1) -> bool:
    """Generate and send the daily Subvurs insights email.

    Returns True on success, False on failure.
    """
    settings = get_settings()
    if not settings.has_email:
        logger.warning("Email not configured, skipping insights report")
        return False

    subject, html, count = build_insights_report(days=days)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_email
    msg["To"] = settings.smtp_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.smtp_email, settings.smtp_app_password)
            server.send_message(msg)
        logger.info("Insights email sent: %s", subject)
        return True
    except Exception:
        logger.exception("Failed to send insights email")
        return False
