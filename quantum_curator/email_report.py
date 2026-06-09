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

CONNECTIONS_TABLE_HEADER = (
    '<div style="margin-top: 24px;">'
    '<h2 style="color: #818cf8; font-size: 18px; margin-bottom: 12px;">Research Connections</h2>'
    '<table style="width: 100%; border-collapse: collapse;"><thead><tr>'
    '<th style="text-align: left; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155; width: 35%;">Article</th>'
    '<th style="text-align: left; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155;">Subvurs Connection</th>'
    '</tr></thead><tbody>'
)

# Phase 3b: surface the top-scored Subvurs-Impact posts at the head of
# the email. subvurs_notes (qualitative) and subvurs_impact_score
# (quantitative, 0.0–1.0) are complementary — notes catch hand-tagged
# connections, impact_score catches what the scorer ranks highly. The
# block only renders when at least one post has a non-zero score, so
# pre-Phase-B emails (all zeros) keep their current layout.
IMPACT_TABLE_HEADER = (
    '<div style="margin-top: 24px;">'
    '<h2 style="color: #06b6d4; font-size: 18px; margin-bottom: 6px;">Top Subvurs-Impact Posts</h2>'
    '<p style="color: #94a3b8; font-size: 12px; margin: 0 0 12px 0;">'
    'Ranked by ``subvurs_impact_score`` (0.0–1.0). Quantitative scorer output, '
    'separate from the qualitative Research Connections below.</p>'
    '<table style="width: 100%; border-collapse: collapse;"><thead><tr>'
    '<th style="text-align: left; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155; width: 60%;">Article</th>'
    '<th style="text-align: right; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155;">Impact</th>'
    '<th style="text-align: left; padding: 8px 12px; color: #94a3b8; border-bottom: 2px solid #334155;">Scorer</th>'
    '</tr></thead><tbody>'
)
# Show this many top-scored entries (rest are still summarized in the
# Research Connections / Other Articles sections below).
IMPACT_TOP_N = 5
# Floor — entries below this don't make the cut even if they're in
# the top N. Matches the "noise floor" pattern from gh_eval (fail-closed
# default).
IMPACT_MIN_SCORE = 0.05

NO_CONNECTIONS_MSG = (
    '<div style="margin-top: 24px; padding: 20px; background: #1e293b; border-radius: 8px; '
    'text-align: center; color: #94a3b8;">No Subvurs research connections found in today\'s articles.</div>'
)

OTHER_TABLE_HEADER = (
    '<div style="margin-top: 24px;">'
    '<h2 style="color: #64748b; font-size: 16px; margin-bottom: 8px;">Other Articles Curated (no connections)</h2>'
    '<table style="width: 100%; border-collapse: collapse;"><tbody>'
)


def _truncate(text: str, limit: int) -> str:
    if len(text) > limit:
        return text[:limit] + "..."
    return text


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
    without_notes = [p for p in posts if not p.subvurs_notes]
    today_str = datetime.utcnow().strftime("%B %d, %Y")
    num_connections = len(with_notes)
    num_posts = len(posts)

    # Phase 3b: top-N by quantitative impact score, gated by IMPACT_MIN_SCORE.
    impact_ranked = sorted(
        [p for p in posts if (p.subvurs_impact_score or 0.0) >= IMPACT_MIN_SCORE],
        key=lambda p: p.subvurs_impact_score or 0.0,
        reverse=True,
    )[:IMPACT_TOP_N]
    num_impact = len(impact_ranked)

    subject = "Quantum Curator: {} Subvurs connections found — {}".format(num_connections, today_str)

    # Build connection rows
    rows = ""
    for p in with_notes:
        date_str = p.published_at.strftime("%Y-%m-%d") if p.published_at else "N/A"
        rows += (
            "<tr>"
            '<td style="padding: 12px; border-bottom: 1px solid #334155; vertical-align: top;">'
            '<a href="{url}" style="color: #818cf8; text-decoration: none; font-weight: 600;">{title}</a>'
            '<br><span style="color: #94a3b8; font-size: 13px;">{source} &middot; {date}</span>'
            "</td>"
            '<td style="padding: 12px; border-bottom: 1px solid #334155; color: #e2e8f0; vertical-align: top; font-size: 14px; line-height: 1.5;">'
            "{notes}"
            "</td>"
            "</tr>"
        ).format(url=p.original_url, title=p.title, source=p.source_name, date=date_str, notes=p.subvurs_notes)

    # Build impact-score rows (Phase 3b)
    impact_rows = ""
    for p in impact_ranked:
        score = p.subvurs_impact_score or 0.0
        version = p.subvurs_impact_version or "unversioned"
        # Color gradient: cyan above 0.5, slate below
        score_color = "#06b6d4" if score >= 0.5 else "#64748b"
        impact_rows += (
            "<tr>"
            '<td style="padding: 12px; border-bottom: 1px solid #334155; vertical-align: top;">'
            '<a href="{url}" style="color: #67e8f9; text-decoration: none; font-weight: 600;">{title}</a>'
            '<br><span style="color: #94a3b8; font-size: 13px;">{source}</span>'
            "</td>"
            '<td style="padding: 12px; border-bottom: 1px solid #334155; color: {score_color}; '
            'font-family: monospace; font-size: 16px; font-weight: 700; text-align: right; vertical-align: top;">'
            "{score:.2f}"
            "</td>"
            '<td style="padding: 12px; border-bottom: 1px solid #334155; color: #94a3b8; '
            'font-size: 12px; vertical-align: top;">'
            "{version}"
            "</td>"
            "</tr>"
        ).format(
            url=p.original_url,
            title=p.title,
            source=p.source_name,
            score_color=score_color,
            score=score,
            version=version,
        )

    if impact_ranked:
        impact_section = IMPACT_TABLE_HEADER + impact_rows + "</tbody></table></div>"
    else:
        impact_section = ""

    # Build no-connection rows
    no_connection_rows = ""
    for p in without_notes:
        title_truncated = _truncate(p.title, 80)
        no_connection_rows += (
            "<tr>"
            '<td style="padding: 6px 12px; border-bottom: 1px solid #1e293b; color: #64748b; font-size: 13px;">'
            "{title}"
            "</td>"
            '<td style="padding: 6px 12px; border-bottom: 1px solid #1e293b; color: #475569; font-size: 13px;">'
            "{source}"
            "</td>"
            "</tr>"
        ).format(title=title_truncated, source=p.source_name)

    # Build connections section
    if with_notes:
        connections_section = CONNECTIONS_TABLE_HEADER + rows + "</tbody></table></div>"
    else:
        connections_section = NO_CONNECTIONS_MSG

    # Build other articles section
    if without_notes:
        other_section = OTHER_TABLE_HEADER + no_connection_rows + "</tbody></table></div>"
    else:
        other_section = ""

    html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        '<head><meta charset="utf-8"></head>\n'
        '<body style="background-color: #0f172a; color: #e2e8f0; '
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        'margin: 0; padding: 20px;">\n'
        '<div style="max-width: 800px; margin: 0 auto;">\n'
        '<div style="text-align: center; padding: 20px 0; border-bottom: 2px solid #6366f1;">\n'
        '<h1 style="color: #6366f1; margin: 0; font-size: 24px;">Quantum Curator &mdash; Subvurs Insights</h1>\n'
        '<p style="color: #94a3b8; margin: 8px 0 0 0;">{today} &middot; {total} articles curated &middot; {connections} connections &middot; {impact} scored</p>\n'
        "</div>\n"
        "{impact_section}\n"
        "{connections_section}\n"
        "{other_section}\n"
        '<div style="margin-top: 30px; padding-top: 16px; border-top: 1px solid #334155; text-align: center; color: #475569; font-size: 12px;">\n'
        'Quantum Curator &middot; Automated daily report &middot; <a href="https://quantumcrier.com" style="color: #6366f1;">quantumcrier.com</a>\n'
        "</div>\n"
        "</div>\n"
        "</body>\n"
        "</html>"
    ).format(
        today=today_str,
        total=num_posts,
        connections=num_connections,
        impact=num_impact,
        impact_section=impact_section,
        connections_section=connections_section,
        other_section=other_section,
    )

    return subject, html, num_connections


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
