from aiogram.types import InlineKeyboardButton as Button
from aiogram.types import InlineKeyboardMarkup as Markup


def water_keyboard() -> Markup:
    return Markup(inline_keyboard=[
        [Button(text=f"+{ml}", callback_data=f"water:{ml}") for ml in (200, 300, 500)],
        [Button(text="↩️ Отменить последнее", callback_data="water:undo")],
    ])


def event_keyboard(event_id: int, kind: str) -> Markup:
    done = "✅ Принял" if kind == "pill" else "✅ Сделал"
    return Markup(inline_keyboard=[
        [Button(text=done, callback_data=f"ev:done:{event_id}")],
        [
            Button(text="⏰ +15 мин", callback_data=f"ev:snooze:{event_id}"),
            Button(text="❌ Пропустить", callback_data=f"ev:skip:{event_id}"),
        ],
    ])


def missed_keyboard(event_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [Button(text="✅ Всё-таки принял", callback_data=f"ev:done:{event_id}")],
    ])


def undo_keyboard(event_id: int) -> Markup:
    return Markup(inline_keyboard=[
        [Button(text="↩️ Отменить отметку", callback_data=f"ev:undo:{event_id}")],
    ])


def tasks_keyboard(tasks: list, day: str) -> Markup:
    rows = []
    for task in tasks:
        rows.append([
            Button(text=f"✅ {task['title'][:24]}", callback_data=f"task:done:{task['id']}:{day}"),
            Button(text="❌", callback_data=f"task:failed:{task['id']}:{day}"),
            Button(text="🗑", callback_data=f"task:del:{task['id']}:{day}"),
        ])
    return Markup(inline_keyboard=rows)


def pills_keyboard(pills: list) -> Markup:
    rows = []
    for pill in pills:
        rows.append([
            Button(text=f"📦 Пополнить: {pill['name'][:20]}", callback_data=f"pill:refill:{pill['id']}"),
            Button(text="⏳ Срок", callback_data=f"pill:course:{pill['id']}"),
            Button(text="🗑", callback_data=f"pill:ask:{pill['id']}"),
        ])
    return Markup(inline_keyboard=rows)


def pill_delete_keyboard(pill_id: int) -> Markup:
    return Markup(inline_keyboard=[[
        Button(text="Да, удалить", callback_data=f"pill:del:{pill_id}"),
        Button(text="Нет", callback_data="pill:keep"),
    ]])


def reminders_keyboard(reminders: list) -> Markup:
    rows = [
        [Button(text=f"🗑 {r['time']} {r['text'][:28]}", callback_data=f"rem:del:{r['id']}")]
        for r in reminders
    ]
    return Markup(inline_keyboard=rows)


def draft_keyboard() -> Markup:
    return Markup(inline_keyboard=[
        [
            Button(text="✅ Записать", callback_data="ai:save"),
            Button(text="✏️ Исправить", callback_data="ai:edit"),
        ],
        [Button(text="Отмена", callback_data="ai:cancel")],
    ])
