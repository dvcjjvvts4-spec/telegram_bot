from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config, repo, reports
from bot.keyboards import pill_delete_keyboard, pills_keyboard
from bot.parsing import parse_number, parse_times, parse_weekdays, weekdays_label

router = Router()


class AddPill(StatesGroup):
    name = State()
    dose = State()
    times = State()
    days = State()
    per_dose = State()
    stock = State()


class Refill(StatesGroup):
    amount = State()


@router.message(Command("pill_add"))
async def start_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddPill.name)
    await message.answer("Название препарата? (выйти: /cancel)")


@router.message(AddPill.name, F.text)
async def got_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip()[:60])
    await state.set_state(AddPill.dose)
    await message.answer("Доза, как написать в напоминании? Например: 1 таблетка, 500 мг")


@router.message(AddPill.dose, F.text)
async def got_dose(message: Message, state: FSMContext) -> None:
    await state.update_data(dose=message.text.strip()[:60])
    await state.set_state(AddPill.times)
    await message.answer("Время приёма. Несколько через запятую: 08:00, 20:00")


@router.message(AddPill.times, F.text)
async def got_times(message: Message, state: FSMContext) -> None:
    times = parse_times(message.text)
    if not times:
        await message.answer("Не понял время. Пример: 08:00, 20:00")
        return
    await state.update_data(times=times)
    await state.set_state(AddPill.days)
    await message.answer("Дни приёма: «каждый день» или список, например: пн, ср, пт")


@router.message(AddPill.days, F.text)
async def got_days(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    days = "" if text in ("каждый день", "ежедневно") else parse_weekdays(text)
    if days is None:
        await message.answer("Напиши «каждый день» или дни, например: пн, ср, пт")
        return
    await state.update_data(days=days)
    await state.set_state(AddPill.per_dose)
    await message.answer("Сколько штук за один приём? Например: 1 или 0,5")


@router.message(AddPill.per_dose, F.text)
async def got_per_dose(message: Message, state: FSMContext) -> None:
    value = parse_number(message.text)
    if value is None or not 0 < value <= 50:
        await message.answer("Нужно число больше нуля, например 1 или 0,5.")
        return
    await state.update_data(per_dose=value)
    await state.set_state(AddPill.stock)
    await message.answer("Сколько штук сейчас в упаковке? Не считать остаток: напиши «-»")


@router.message(AddPill.stock, F.text)
async def got_stock(message: Message, state: FSMContext, db: repo.Db) -> None:
    text = message.text.strip()
    stock = None if text == "-" else parse_number(text)
    if text != "-" and (stock is None or stock < 0):
        await message.answer("Нужно число или «-».")
        return
    data = await state.get_data()
    await state.clear()
    await repo.add_pill(
        db, data["name"], data["dose"], data["per_dose"], stock,
        data["times"], data["days"], int(config.now().timestamp()),
    )
    await message.answer(
        f"Добавил: {data['name']}, {data['dose']}\n"
        f"Время: {', '.join(data['times'])}, {weekdays_label(data['days'])}\n"
        "Приёмы, время которых сегодня уже прошло, начнутся со следующего раза."
    )


async def pills_text(db: repo.Db, pills: list) -> str:
    rows = []
    for pill in pills:
        alarms = await repo.pill_alarms(db, pill["id"])
        times = ", ".join(a["time"] for a in alarms)
        days = weekdays_label(alarms[0]["weekdays"]) if alarms else ""
        row = f"💊 {pill['name']}, {pill['dose']}\n   {times}, {days}"
        left = await repo.pill_days_left(db, pill)
        if left is not None:
            row += f"\n   Остаток: {pill['stock']:g} шт., примерно на {int(left)} дн."
        rows.append(row)
    today_block = await reports.pills_block(db, config.today())
    return "\n".join(rows) + (f"\n\n{today_block}" if today_block else "")


@router.message(Command("pills"))
async def cmd_pills(message: Message, db: repo.Db) -> None:
    pills = await repo.list_pills(db)
    if not pills:
        await message.answer("Таблеток пока нет. Добавить: /pill_add")
        return
    await message.answer(await pills_text(db, pills), reply_markup=pills_keyboard(pills))


@router.message(Command("pill_log"))
async def cmd_log(message: Message, db: repo.Db) -> None:
    rows = await repo.pill_journal(db, repo.journal_since(config.today(), 7))
    if not rows:
        await message.answer("За 7 дней записей нет.")
        return
    lines = []
    for row in rows:
        taken = (
            f" (отмечено в {reports.format_ts(row['resolved_at'])})"
            if row["status"] == "done" and row["resolved_at"] else ""
        )
        lines.append(
            f"{reports.STATUS_ICONS[row['status']]} {row['day'][8:]}.{row['day'][5:7]} "
            f"{row['time']} {row['name']}{taken}"
        )
    done = sum(1 for r in rows if r["status"] == "done")
    closed = sum(1 for r in rows if r["status"] != "pending")
    await message.answer(f"Принято {done} из {closed}\n\n" + "\n".join(lines[:60]))


@router.callback_query(F.data.startswith("pill:ask:"))
async def ask_delete(callback: CallbackQuery, db: repo.Db) -> None:
    pill = await repo.get_pill(db, int(callback.data.split(":")[2]))
    await callback.message.answer(
        f"Удалить {pill['name']}? Журнал приёмов сохранится.",
        reply_markup=pill_delete_keyboard(pill["id"]),
    )
    await callback.answer()


@router.callback_query(F.data == "pill:keep")
async def keep_pill(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Оставил.")
    await callback.answer()


@router.callback_query(F.data.startswith("pill:del:"))
async def delete_pill(callback: CallbackQuery, db: repo.Db) -> None:
    await repo.delete_pill(db, int(callback.data.split(":")[2]))
    await callback.message.edit_text("Удалено, напоминаний больше не будет.")
    await callback.answer()


@router.callback_query(F.data.startswith("pill:refill:"))
async def ask_refill(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Refill.amount)
    await state.update_data(pill_id=int(callback.data.split(":")[2]))
    await callback.message.answer("Сколько штук добавить?")
    await callback.answer()


@router.message(Refill.amount, F.text)
async def got_refill(message: Message, state: FSMContext, db: repo.Db) -> None:
    amount = parse_number(message.text)
    if amount is None or amount <= 0:
        await message.answer("Нужно положительное число.")
        return
    data = await state.get_data()
    await state.clear()
    stock = await repo.refill_pill(db, data["pill_id"], amount)
    await message.answer(f"Остаток: {stock:g} шт.")
