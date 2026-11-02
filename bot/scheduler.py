"""Фоновый цикл. Всё его состояние лежит в базе, поэтому перезапуск ничего не теряет."""

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError

from bot import config, repo, reports
from bot.keyboards import event_keyboard, missed_keyboard
from bot.parsing import parse_time

log = logging.getLogger(__name__)
TICK_SECONDS = 20
LATE_NOTICE_MINUTES = 10
SEND_ERRORS = (TelegramAPIError, TelegramNetworkError)


def occurs_on(alarm, day: date) -> bool:
    if alarm["date"]:
        return alarm["date"] == day.isoformat()
    return not alarm["weekdays"] or str(day.weekday()) in alarm["weekdays"].split(",")


def due_at(alarm, day: date) -> datetime:
    hours, minutes = map(int, alarm["time"].split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=config.TZ)


async def create_due_events(db: repo.Db, now: datetime) -> None:
    """Вчерашний день проверяется тоже: приём в 23:30 не потеряется при сбое ночью."""
    now_ts = int(now.timestamp())
    for alarm in await repo.active_alarms(db):
        for day in (now.date() - timedelta(days=1), now.date()):
            due = due_at(alarm, day)
            if occurs_on(alarm, day) and alarm["created_at"] <= due.timestamp() <= now_ts:
                await repo.create_event(db, alarm["id"], day, now_ts)


def event_text(event, now: datetime) -> str:
    if event["kind"] == "reminder":
        return f"🔔 {event['text']}"
    rows = [f"💊 Пора принять: {event['name']}, {event['dose']}"]
    rows.append(f"По расписанию: {event['time']}, {date.fromisoformat(event['day']):%d.%m}")
    if event["pings"]:
        rows.append(f"Повтор {event['pings'] + 1} из {config.PILL_MAX_PINGS}")
    due = due_at({"time": event["time"]}, date.fromisoformat(event["day"]))
    if not event["pings"] and now - due > timedelta(minutes=LATE_NOTICE_MINUTES):
        rows.append("Напоминание пришло с опозданием. Проверь, не принял ли ты уже эту дозу.")
    return "\n".join(rows)


async def clear_buttons(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Старые кнопки убираем для порядка, поэтому ошибка здесь не критична."""
    if message_id:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id)
        except SEND_ERRORS:
            log.debug("Не удалось убрать кнопки у сообщения %s", message_id)


async def deliver_events(db: repo.Db, bot: Bot, chat_id: int, now: datetime) -> None:
    now_ts = int(now.timestamp())
    for event in await repo.due_events(db, now_ts):
        is_pill = event["kind"] == "pill"

        if is_pill and event["pings"] >= config.PILL_MAX_PINGS:
            sent = await bot.send_message(
                chat_id,
                f"❌ Приём не отмечен: {event['name']}, {event['dose']} "
                f"({event['time']}). Записал как пропущенный.\n"
                "Если доза пропущена, смотри инструкцию к препарату или спроси врача.",
                reply_markup=missed_keyboard(event["id"]),
            )
            await repo.mark_missed(db, event["id"], now_ts)
            await clear_buttons(bot, chat_id, event["message_id"])
            await repo.event_sent(db, event["id"], event["pings"], None, sent.message_id)
            continue

        sent = await bot.send_message(
            chat_id, event_text(event, now), reply_markup=event_keyboard(event["id"], event["kind"])
        )
        await clear_buttons(bot, chat_id, event["message_id"])
        next_at = now_ts + config.PILL_REPEAT_MINUTES * 60 if is_pill else None
        await repo.event_sent(db, event["id"], event["pings"] + 1, next_at, sent.message_id)


async def send_summaries(db: repo.Db, bot: Bot, chat_id: int, now: datetime) -> None:
    settings = await repo.get_settings(db)
    day = now.date()
    today = day.isoformat()
    current = now.strftime("%H:%M")
    morning = parse_time(settings["morning_time"])
    evening = parse_time(settings["evening_time"])

    # Утреннюю сводку отправляем и с опозданием, но не позже вечерней.
    if morning <= current < evening and settings["last_morning"] != today:
        await bot.send_message(chat_id, await reports.morning_report(db, day))
        await repo.mark_summary_sent(db, "last_morning", day)
    if current >= evening and settings["last_evening"] != today:
        await bot.send_message(chat_id, await reports.evening_report(db, day))
        await repo.mark_summary_sent(db, "last_evening", day)


async def tick(db: repo.Db, bot: Bot, chat_id: int, now: datetime) -> None:
    if (await repo.get_settings(db))["autocarry"]:
        await repo.carry_over_tasks(db, now.date())
    await create_due_events(db, now)
    await deliver_events(db, bot, chat_id, now)
    await send_summaries(db, bot, chat_id, now)


async def run_scheduler(db: repo.Db, bot: Bot, chat_id: int) -> None:
    while True:
        try:
            await tick(db, bot, chat_id, config.now())
        except Exception:
            # Цикл должен пережить сбой сети: неотправленное уйдёт на следующем шаге.
            log.exception("Ошибка в планировщике")
        await asyncio.sleep(TICK_SECONDS)
