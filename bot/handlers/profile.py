from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import config, repo, reports
from bot.nutrition import ACTIVITY_LABELS
from bot.parsing import parse_number, parse_weight

router = Router()


class Form(StatesGroup):
    weight = State()
    height = State()
    age = State()
    sex = State()
    activity = State()
    target = State()


ACTIVITY_QUESTION = "Уровень активности, число от 1 до 5:\n" + "\n".join(
    f"{level}. {label}" for level, label in ACTIVITY_LABELS.items()
)


def in_range(text: str, low: float, high: float) -> float | None:
    value = parse_number(text)
    return value if value is not None and low <= value <= high else None


@router.message(Command("profile"))
async def start_form(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.weight)
    await message.answer("Заполним профиль. Текущий вес в кг? (выйти: /cancel)")


@router.message(Form.weight)
async def got_weight(message: Message, state: FSMContext) -> None:
    value = in_range(message.text or "", 20, 400)
    if value is None:
        await message.answer("Нужно число от 20 до 400, например 82,5.")
        return
    await state.update_data(weight=value)
    await state.set_state(Form.height)
    await message.answer("Рост в см?")


@router.message(Form.height)
async def got_height(message: Message, state: FSMContext) -> None:
    value = in_range(message.text or "", 100, 250)
    if value is None:
        await message.answer("Нужно число от 100 до 250.")
        return
    await state.update_data(height=value)
    await state.set_state(Form.age)
    await message.answer("Возраст?")


@router.message(Form.age)
async def got_age(message: Message, state: FSMContext) -> None:
    value = in_range(message.text or "", 14, 100)
    if value is None:
        await message.answer("Нужно число от 14 до 100.")
        return
    await state.update_data(age=int(value))
    await state.set_state(Form.sex)
    await message.answer("Пол: м или ж?")


@router.message(Form.sex)
async def got_sex(message: Message, state: FSMContext) -> None:
    sex = {"м": "m", "ж": "f"}.get((message.text or "").strip().lower())
    if sex is None:
        await message.answer("Напиши м или ж.")
        return
    await state.update_data(sex=sex)
    await state.set_state(Form.activity)
    await message.answer(ACTIVITY_QUESTION)


@router.message(Form.activity)
async def got_activity(message: Message, state: FSMContext) -> None:
    value = in_range(message.text or "", 1, 5)
    if value is None or value != int(value):
        await message.answer("Нужно целое число от 1 до 5.")
        return
    await state.update_data(activity=int(value))
    await state.set_state(Form.target)
    await message.answer("Желаемый вес в кг?")


@router.message(Form.target)
async def got_target(message: Message, state: FSMContext, db: repo.Db) -> None:
    value = in_range(message.text or "", 20, 400)
    if value is None:
        await message.answer("Нужно число от 20 до 400.")
        return
    data = await state.get_data()
    await state.clear()
    await repo.save_profile(
        db, data["weight"], data["height"], data["age"], data["sex"], data["activity"], value
    )
    await repo.add_weight(db, config.today(), data["weight"])
    await message.answer("Профиль сохранён.\n\n" + await norms_text(db))


async def norms_text(db: repo.Db) -> str:
    norms = await repo.get_norms(db)
    text = (
        f"Цель: {norms.goal}\n"
        f"Базовый обмен: {norms.bmr} ккал, поддержание: {norms.maintenance} ккал\n"
        f"Норма в день: {norms.kcal} ккал, Б {norms.protein} / Ж {norms.fat} / "
        f"У {norms.carbs} г, вода {norms.water_ml} мл"
    )
    if norms.floored:
        text += "\n⚠️ Норма поднята до базового обмена: ниже опускаться небезопасно."
    return text


@router.message(Command("weight"))
async def cmd_weight(message: Message, db: repo.Db) -> None:
    argument = (message.text or "").partition(" ")[2]
    if argument:
        kg = parse_weight(f"вес {argument}")
        if kg is None:
            await message.answer("Пример: /weight 82,5")
            return
        await repo.add_weight(db, config.today(), kg)
    await message.answer(await reports.weight_report(db, config.today()))
