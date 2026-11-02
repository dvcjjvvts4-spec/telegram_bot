"""Тексты сводок. Их используют и команды, и планировщик."""

from datetime import date, datetime, timedelta

from bot import nutrition, repo
from bot.config import TZ

STATUS_ICONS = {"pending": "⏳", "done": "✅", "skipped": "⏭", "missed": "❌"}
TASK_ICONS = {None: "⬜", "done": "✅", "failed": "❌"}


def bar(value: float, target: float, width: int = 10) -> str:
    share = min(value / target, 1) if target > 0 else 0
    filled = round(share * width)
    return "█" * filled + "░" * (width - filled)


def line(label: str, value: float, target: float, unit: str) -> str:
    return f"{label:<8} {bar(value, target)} {round(value)}/{round(target)} {unit}"


async def nutrition_block(db: repo.Db, day: date) -> str:
    norms = await repo.get_norms(db)
    if not norms:
        return "Профиль не заполнен: /profile"
    totals = await repo.day_totals(db, day)
    water = await repo.water_total(db, day)
    activity = await repo.get_activity(db, day)
    bonus = (activity["active_kcal"] or 0) if activity else 0
    rows = [
        line("Калории", totals["kcal"], norms.kcal + bonus, "ккал"),
        line("Белки", totals["protein"], norms.protein, "г"),
        line("Жиры", totals["fat"], norms.fat, "г"),
        line("Углеводы", totals["carbs"], norms.carbs, "г"),
        line("Вода", water, norms.water_ml, "мл"),
    ]
    if bonus:
        rows.append(f"Активность с часов: +{round(bonus)} ккал к норме")
    return "\n".join(rows)


async def pills_block(db: repo.Db, day: date) -> str:
    events = await repo.pill_events_for_day(db, day)
    if not events:
        return ""
    rows = [
        f"{STATUS_ICONS[e['status']]} {e['time']} {e['name']}, {e['dose']}" for e in events
    ]
    return "Таблетки:\n" + "\n".join(rows)


async def tasks_block(db: repo.Db, day: date) -> str:
    tasks = await repo.tasks_for_day(db, day)
    if not tasks:
        return "Задач нет"
    return "Задачи:\n" + "\n".join(f"{TASK_ICONS[t['status']]} {t['title']}" for t in tasks)


async def today_report(db: repo.Db, day: date) -> str:
    parts = [
        f"Сегодня, {day:%d.%m}",
        await nutrition_block(db, day),
        await pills_block(db, day),
        await tasks_block(db, day),
    ]
    return "\n\n".join(p for p in parts if p)


async def schedule_block(db: repo.Db, day: date) -> str:
    """Расписание приёмов на день, включая ещё не наступившие."""
    weekday = str(day.weekday())
    rows = []
    for pill in await repo.list_pills(db):
        for alarm in await repo.pill_alarms(db, pill["id"]):
            if not alarm["weekdays"] or weekday in alarm["weekdays"].split(","):
                rows.append(f"{alarm['time']} {pill['name']}, {pill['dose']}")
    return "Таблетки на сегодня:\n" + "\n".join(sorted(rows)) if rows else ""


async def morning_report(db: repo.Db, day: date) -> str:
    parts = [
        "Доброе утро! План на сегодня.",
        await tasks_block(db, day),
        await schedule_block(db, day),
    ]
    return "\n\n".join(p for p in parts if p)


async def evening_report(db: repo.Db, day: date) -> str:
    open_tasks = [t for t in await repo.tasks_for_day(db, day) if t["status"] is None]
    tasks = (
        "Не отмечено:\n" + "\n".join(f"⬜ {t['title']}" for t in open_tasks)
        if open_tasks else "Все задачи на сегодня отмечены."
    )
    parts = [
        "Итог дня.",
        await nutrition_block(db, day),
        await pills_block(db, day),
        tasks + ("\n\nОтметить: /tasks" if open_tasks else ""),
    ]
    return "\n\n".join(p for p in parts if p)


async def weight_report(db: repo.Db, day: date) -> str:
    profile = await repo.get_profile(db)
    norms = await repo.get_norms(db)
    if not profile or not norms:
        return "Профиль не заполнен: /profile"
    current, target = profile["weight_kg"], profile["target_kg"]
    percent = nutrition.progress_percent(profile["start_weight_kg"], current, target)
    weekly = nutrition.weekly_change(await repo.weight_points(db, day - timedelta(days=28)))

    rows = [
        f"Вес: {current:g} кг, цель: {target:g} кг",
        f"Прогресс: {bar(percent, 100)} {percent}%",
        f"Норма: {norms.kcal} ккал, Б {norms.protein} / Ж {norms.fat} / У {norms.carbs} г, "
        f"вода {norms.water_ml} мл",
    ]
    if weekly is not None:
        rows.append(f"Тренд: {weekly:+.2f} кг в неделю")
    date_goal = nutrition.forecast_date(current, target, weekly, day)
    if date_goal:
        rows.append(f"Прогноз достижения цели: {date_goal:%d.%m.%Y}")
    if nutrition.too_fast_loss(weekly, current):
        rows.append("⚠️ Вес снижается быстрее ~1% в неделю. Стоит поднять калорийность.")
    return "\n".join(rows)


def format_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
