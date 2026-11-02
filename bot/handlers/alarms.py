"""Кнопки напоминаний и команды настройки."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot import config, repo, reports
from bot.keyboards import event_keyboard, reminders_keyboard, undo_keyboard
from bot.parsing import parse_remind, parse_time, weekdays_label

router = Router()
SNOOZE_MINUTES = 15


def event_title(event) -> str:
    if event["kind"] == "pill":
        return f"{event['name']}, {event['dose']} ({event['time']})"
    return event["text"]


async def stock_warning(db: repo.Db, pill_id: int) -> str:
    pill = await repo.get_pill(db, pill_id)
    left = await repo.pill_days_left(db, pill)
    if left is None or left > config.LOW_STOCK_DAYS:
        return ""
    return f"\n⚠️ {pill['name']} заканчивается: {pill['stock']:g} шт., примерно на {int(left)} дн."


@router.callback_query(F.data.startswith("ev:"))
async def event_button(callback: CallbackQuery, db: repo.Db) -> None:
    _, action, raw_id = callback.data.split(":")
    event_id = int(raw_id)
    event = await repo.get_event(db, event_id)
    if not event:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    now_ts = int(config.now().timestamp())

    if action == "snooze":
        if await repo.snooze_event(db, event_id, now_ts + SNOOZE_MINUTES * 60):
            await callback.message.edit_text(
                f"⏰ Напомню через {SNOOZE_MINUTES} мин: {event_title(event)}"
            )
        await callback.answer()
        return

    if action == "undo":
        previous = event["status"]
        if not await repo.undo_event(db, event_id):
            await callback.answer("Отметка уже изменена")
            return
        if previous == "done" and event["kind"] == "pill":
            await repo.restore_stock(db, event["pill_id"], event["per_dose"])
        await callback.message.edit_text(
            f"Отметка отменена: {event_title(event)}",
            reply_markup=event_keyboard(event_id, event["kind"]),
        )
        await callback.answer()
        return

    status = "done" if action == "done" else "skipped"
    if not await repo.finish_event(db, event_id, status, now_ts):
        # Защита от двойной дозы: повторное нажатие не создаёт вторую отметку.
        notice = (
            f"Уже отмечено в {reports.format_ts(event['resolved_at'])}"
            if event["resolved_at"] else "Эта запись уже закрыта"
        )
        await callback.answer(notice, show_alert=True)
        return

    icon = "✅" if status == "done" else "⏭"
    text = f"{icon} {event_title(event)}, {reports.format_ts(now_ts)}"
    if status == "done" and event["kind"] == "pill":
        text += await stock_warning(db, event["pill_id"])
    keyboard = undo_keyboard(event_id) if event["kind"] == "pill" else None
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.message(Command("remind"))
async def cmd_remind(message: Message, db: repo.Db) -> None:
    parsed = parse_remind((message.text or "").partition(" ")[2], config.today())
    if not parsed:
        await message.answer(
            "Примеры:\n/remind 18:30 позвонить\n/remind пн,ср 19:00 тренировка\n"
            "/remind завтра 10:00 дело\n/remind 12.11 09:00 врач"
        )
        return
    when, time, text = parsed
    await repo.add_reminder(db, text, time, when, int(config.now().timestamp()))
    label = f"{when.date:%d.%m.%Y}" if when.date else weekdays_label(when.weekdays)
    await message.answer(f"Напомню: {text}\n{time}, {label}")


@router.message(Command("reminders"))
async def cmd_reminders(message: Message, db: repo.Db) -> None:
    reminders = await repo.list_reminders(db, config.today())
    if not reminders:
        await message.answer("Напоминаний нет. Создать: /remind 18:30 текст")
        return
    rows = [
        f"🔔 {r['time']}, "
        f"{r['date'] if r['date'] else weekdays_label(r['weekdays'])}: {r['text']}"
        for r in reminders
    ]
    await message.answer(
        "\n".join(rows) + "\n\nНажми кнопку, чтобы удалить.",
        reply_markup=reminders_keyboard(reminders),
    )


@router.callback_query(F.data.startswith("rem:del:"))
async def delete_reminder(callback: CallbackQuery, db: repo.Db) -> None:
    await repo.delete_reminder(db, int(callback.data.split(":")[2]))
    reminders = await repo.list_reminders(db, config.today())
    if reminders:
        await callback.message.edit_reply_markup(reply_markup=reminders_keyboard(reminders))
    else:
        await callback.message.edit_text("Напоминаний нет.")
    await callback.answer("Удалено")


@router.message(Command("summary"))
async def cmd_summary(message: Message, db: repo.Db) -> None:
    parts = (message.text or "").split()[1:]
    times = [parse_time(p) for p in parts]
    if len(times) != 2 or None in times or times[0] >= times[1]:
        settings = await repo.get_settings(db)
        await message.answer(
            f"Сейчас: утро {settings['morning_time']}, вечер {settings['evening_time']}.\n"
            "Изменить: /summary 08:00 21:00"
        )
        return
    await repo.set_summary_times(db, times[0], times[1])
    await message.answer(f"Сводки: {times[0]} и {times[1]}")
