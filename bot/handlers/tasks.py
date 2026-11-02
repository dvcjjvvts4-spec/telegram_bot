from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot import config, repo, reports
from bot.keyboards import tasks_keyboard
from bot.parsing import parse_task, weekdays_label

router = Router()


def describe_when(when) -> str:
    if when.kind == "daily":
        return "каждый день"
    if when.kind == "weekly":
        return weekdays_label(when.weekdays)
    return f"{when.date:%d.%m.%Y}"


async def add_from_text(message: Message, db: repo.Db, text: str) -> bool:
    parsed = parse_task(text, config.today())
    if not parsed:
        return False
    when, title = parsed
    await repo.add_task(db, title, when)
    await message.answer(f"Задача добавлена: {title} ({describe_when(when)})")
    return True


async def render(db: repo.Db, day: date) -> tuple[str, object]:
    tasks = await repo.tasks_for_day(db, day)
    return await reports.tasks_block(db, day), tasks_keyboard(tasks, day.isoformat())


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, db: repo.Db) -> None:
    text, keyboard = await render(db, config.today())
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("task"))
async def cmd_task(message: Message, db: repo.Db) -> None:
    if not await add_from_text(message, db, (message.text or "").partition(" ")[2]):
        await message.answer(
            "Примеры:\n/task чт: забрать посылку\n/task 12.10: врач\n"
            "/task пн,ср: английский\n/task каждый день: зарядка"
        )


@router.message(Command("carry"))
async def cmd_carry(message: Message, db: repo.Db) -> None:
    argument = (message.text or "").partition(" ")[2].strip().lower()
    if argument not in ("on", "off"):
        enabled = (await repo.get_settings(db))["autocarry"]
        await message.answer(
            f"Автоперенос {'включён' if enabled else 'выключен'}. "
            "Изменить: /carry on или /carry off"
        )
        return
    await repo.set_autocarry(db, argument == "on")
    await message.answer("Сохранено.")


@router.callback_query(F.data.startswith("task:"))
async def task_button(callback: CallbackQuery, db: repo.Db) -> None:
    _, action, task_id, day_text = callback.data.split(":")
    day = date.fromisoformat(day_text)
    await callback.answer()
    if action == "del":
        await repo.delete_task(db, int(task_id))
    else:
        await repo.set_task_status(db, int(task_id), day, action)
    text, keyboard = await render(db, day)
    await callback.message.edit_text(text, reply_markup=keyboard)
