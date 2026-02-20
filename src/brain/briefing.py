"""
briefing.py — Daily morning summary.

Scans the vault for open actions, recent captures, and media backlog,
then posts a concise summary to Telegram at a configurable time.
"""

import asyncio
import logging
import os
import random
import threading
from datetime import date, datetime

import schedule


def _build_briefing(vault) -> str:
    """
    Build a concise daily briefing message.

    Priority order:
    1. Overdue actions
    2. Actions due today
    3. Upcoming deadlines (next 3 days)
    4. Yesterday's captures
    5. One random media suggestion
    """
    today = date.today()
    sections = []

    # ---- Actions ----
    actions = vault.scan_actions()
    overdue = []
    due_today = []
    upcoming = []

    for a in actions:
        if a["status"] in ("done", "completed"):
            continue

        due = a.get("due_date")
        if not due:
            continue

        try:
            due_date = datetime.strptime(due, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        diff = (due_date - today).days

        if diff < 0:
            overdue.append((a, diff))
        elif diff == 0:
            due_today.append(a)
        elif diff <= 3:
            upcoming.append((a, diff))

    if overdue:
        overdue.sort(key=lambda x: x[1])
        lines = []
        for a, diff in overdue:
            project = f" ({a['project']})" if a.get("project") else ""
            lines.append(f"  • ‼️ {a['title']}{project} — {abs(diff)}d overdue")
        sections.append("*🔴 Overdue*\n" + "\n".join(lines))

    if due_today:
        lines = []
        for a in due_today:
            project = f" ({a['project']})" if a.get("project") else ""
            priority = f" [{a['priority']}]" if a.get("priority") else ""
            lines.append(f"  • {a['title']}{project}{priority}")
        sections.append("*📌 Due Today*\n" + "\n".join(lines))

    if upcoming:
        upcoming.sort(key=lambda x: x[1])
        lines = []
        for a, diff in upcoming:
            project = f" ({a['project']})" if a.get("project") else ""
            lines.append(f"  • {a['title']}{project} — in {diff}d")
        sections.append("*📅 Upcoming*\n" + "\n".join(lines))

    # ---- Recent captures ----
    recent = vault.scan_recent(hours=24)
    if recent:
        lines = [f"  • {r['title']} → `{r['folder']}/`" for r in recent[:5]]
        if len(recent) > 5:
            lines.append(f"  _...and {len(recent) - 5} more_")
        sections.append("*📥 Yesterday's Captures*\n" + "\n".join(lines))

    # ---- Media suggestion ----
    backlog = vault.scan_media_backlog()
    if backlog:
        pick = random.choice(backlog)
        sections.append(
            f"*🎬 Maybe today?*\n  • _{pick['title']}_ ({pick['media_type']})"
        )

    if not sections:
        return "☀️ All clear — nothing urgent today!"

    header = f"*☀️ Morning Briefing — {today.strftime('%A %d %B')}*\n"
    return header + "\n\n".join(sections)


def _run_briefing(bot, vault, chat_id: str):
    """Post the daily briefing to Telegram."""
    try:
        message = _build_briefing(vault)
        asyncio.run(
            bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
        )
        logging.info("📬 Daily briefing posted")
    except Exception as e:
        logging.exception(f"Failed to post daily briefing: {e}")


def _scheduler_loop():
    """Run the schedule loop forever (designed for a daemon thread)."""
    import time

    while True:
        schedule.run_pending()
        time.sleep(30)


def start_scheduler(bot, vault):
    """
    Start the daily briefing scheduler in a background daemon thread.

    Posts to the chat defined by BRIEFING_CHAT_ID env var.
    """
    briefing_time = os.environ.get("BRIEFING_TIME", "07:00")
    chat_id = os.environ.get("BRIEFING_CHAT_ID", "")

    if not chat_id:
        logging.warning(
            "BRIEFING_CHAT_ID not set — daily briefing disabled. "
            "Set it to a Telegram chat ID to enable."
        )
        return

    schedule.every().day.at(briefing_time).do(
        _run_briefing, bot=bot, vault=vault, chat_id=chat_id
    )

    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    logging.info(f"📅 Daily briefing scheduled at {briefing_time} → {chat_id}")
