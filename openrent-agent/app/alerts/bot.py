"""
Telegram bot: password-gated auth flow, /resolve, /unsubscribe, /status, and
the broadcaster the AlertManager sends through. Long-polling (no public URL
needed) — runs alongside the AlertManager and health-check loops in the same
process (see scripts/run_alert_bot.py).
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.alerts import health_checks, registry
from app.alerts.manager import AlertManager
from app.config import settings
from app.utils.logger import logger


def _chat_id(update: Update) -> str:
    return str(update.effective_chat.id)


async def _start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    subscriber = registry.get_or_create_pending(_chat_id(update), chat.username, chat.first_name)
    if subscriber.authorized:
        await update.message.reply_text("You're already subscribed to alerts.")
        return
    await update.message.reply_text("Send the access password to subscribe to alerts.")


async def _unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    registry.unsubscribe(_chat_id(update))
    await update.message.reply_text("Unsubscribed. Send /start any time to resubscribe.")


async def _password_attempt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    chat_id = _chat_id(update)
    subscriber = registry.get_or_create_pending(chat_id, chat.username, chat.first_name)

    if subscriber.authorized:
        # Authorized users' plain text isn't a command we understand; ignore.
        return

    locked, retry_after = registry.is_locked_out(chat_id)
    if locked:
        minutes = max(1, retry_after // 60)
        await update.message.reply_text(f"Too many attempts. Try again in ~{minutes} min.")
        return

    password = (update.message.text or "").strip()
    if registry.check_password(password):
        registry.authorize(chat_id)
        await update.message.reply_text("Password accepted — you're subscribed to alerts.")
        return

    attempts, now_locked = registry.record_failed_attempt(chat_id)
    if now_locked:
        await update.message.reply_text("Too many wrong attempts. Locked out for a while.")
    else:
        await update.message.reply_text("Wrong password. Try again.")


def _format_status(manager: AlertManager) -> str:
    summary = manager.status_summary()
    lines = [
        f"Events today: {summary['events_today']}",
        f"Subscribers: {registry.count_authorized()}",
    ]
    if summary["active_incidents"]:
        lines.append("Active incidents:")
        lines.extend(f"- {i}" for i in summary["active_incidents"])
    else:
        lines.append("No active incidents.")
    return "\n".join(lines)


def register_handlers(application: Application, manager: AlertManager) -> None:
    async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        subscriber = registry.get_subscriber(_chat_id(update))
        if not subscriber or not subscriber.authorized:
            await update.message.reply_text("Not authorized.")
            return
        keyword = " ".join(context.args) if context.args else None
        result = manager.resolve(keyword)
        if not keyword:
            text = "No open manual incidents." if not result else (
                "Open incidents:\n" + "\n".join(f"- {r}" for r in result)
            )
        elif not result:
            text = f"No open incident matched '{keyword}'."
        else:
            text = "Resolved:\n" + "\n".join(f"- {r}" for r in result)
        await update.message.reply_text(text)

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        subscriber = registry.get_subscriber(_chat_id(update))
        if not subscriber or not subscriber.authorized:
            await update.message.reply_text("Not authorized.")
            return
        await update.message.reply_text(_format_status(manager))

    application.add_handler(CommandHandler("start", _start_command))
    application.add_handler(CommandHandler("unsubscribe", _unsubscribe_command))
    application.add_handler(CommandHandler("resolve", resolve_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _password_attempt_handler))


def build_application(manager: AlertManager) -> Application:
    """Build a fresh Application wired to `manager`. Used by run_alert_bot()
    and available standalone for tests that supply a fake manager/broadcast."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    register_handlers(application, manager)
    return application


def make_broadcaster(application: Application):
    async def send_alert_to_all(text: str) -> None:
        subscribers = await asyncio.to_thread(registry.get_authorized_subscribers)
        for subscriber in subscribers:
            try:
                await application.bot.send_message(
                    chat_id=subscriber.chat_id, text=text, parse_mode="Markdown"
                )
            except Forbidden:
                logger.warning(f"ALERT_SEND_BLOCKED chat_id={subscriber.chat_id} — deactivating")
                await asyncio.to_thread(registry.deactivate, subscriber.chat_id)
            except BadRequest as exc:
                logger.warning(f"ALERT_SEND_BAD_REQUEST chat_id={subscriber.chat_id} error={exc}")
            except Exception:
                logger.exception(f"ALERT_SEND_FAILED chat_id={subscriber.chat_id}")

    return send_alert_to_all


async def _daily_heartbeat(manager: AlertManager, broadcast) -> None:
    interval_seconds = settings.ALERT_HEARTBEAT_HOURS * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await broadcast("💓 Daily heartbeat — alert bot is up.\n\n" + _format_status(manager))
        except Exception:
            logger.exception("ALERT_DAILY_HEARTBEAT_FAILED")


async def run_alert_bot() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    # Application must exist before AlertManager (broadcast needs application.bot),
    # and AlertManager must exist before the command handlers are registered
    # (they close over it) — so build bare, then wire, then register.
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    broadcast = make_broadcaster(application)
    manager = AlertManager(broadcast=broadcast)
    register_handlers(application, manager)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("ALERT_BOT_POLLING_STARTED")

    try:
        await asyncio.gather(
            manager.run_forever(),
            health_checks.run_forever(manager),
            _daily_heartbeat(manager, broadcast),
        )
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
