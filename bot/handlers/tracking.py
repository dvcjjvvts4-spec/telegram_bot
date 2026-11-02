"""Сводка, вода и ручная запись еды."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot import config, repo, reports
from bot.keyboards import water_keyboard
from bot.parsing import parse_meal

router = Router()


async def water_text(db: repo.Db) -> str:
    day = config.today()
    total = await repo.water_total(db, day)
    norms = await repo.get_norms(db)
    if not norms:
        return f"Вода сегодня: {total} мл"
    return reports.line("Вода", total, norms.water_ml, "мл")


@router.message(Command("today"))
async def cmd_today(message: Message, db: repo.Db) -> None:
    await message.answer(await reports.today_report(db, config.today()))


@router.message(Command("water"))
async def cmd_water(message: Message, db: repo.Db) -> None:
    await message.answer(await water_text(db), reply_markup=water_keyboard())


@router.callback_query(F.data.startswith("water:"))
async def water_button(callback: CallbackQuery, db: repo.Db) -> None:
    value = callback.data.split(":")[1]
    day = config.today()
    if value == "undo":
        removed = await repo.undo_water(db, day)
        await callback.answer(f"Убрал {removed} мл" if removed else "Нечего отменять")
    else:
        await repo.add_water(db, day, int(value))
        await callback.answer(f"+{value} мл")
    await callback.message.edit_text(await water_text(db), reply_markup=water_keyboard())


@router.message(Command("meal"))
async def cmd_meal(message: Message, db: repo.Db) -> None:
    meal = parse_meal((message.text or "").partition(" ")[2])
    if not meal:
        await message.answer(
            "Формат: /meal Гречка; 350\nИли с БЖУ: /meal Гречка; 350; 12; 4; 60"
        )
        return
    await repo.add_meal(db, config.today(), **meal)
    await message.answer(f"Записал: {meal['name']}, {meal['kcal']:g} ккал")
