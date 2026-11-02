"""Все SQL-запросы в одном месте: обработчики не знают про устройство таблиц."""

from datetime import date, timedelta

import aiosqlite

from bot.nutrition import Norms, calc_norms
from bot.parsing import When

Db = aiosqlite.Connection


async def _one(db: Db, sql: str, *args):
    async with db.execute(sql, args) as cursor:
        return await cursor.fetchone()


async def _all(db: Db, sql: str, *args):
    async with db.execute(sql, args) as cursor:
        return await cursor.fetchall()


# --- Профиль и настройки ---

async def get_profile(db: Db):
    return await _one(db, "SELECT * FROM profile WHERE id = 1")


async def save_profile(
    db: Db, weight: float, height: float, age: int, sex: str, activity: int, target: float
) -> None:
    await db.execute(
        """INSERT INTO profile
           (id, weight_kg, start_weight_kg, target_kg, height_cm, age, sex, activity)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (id) DO UPDATE SET
             weight_kg = excluded.weight_kg, start_weight_kg = excluded.start_weight_kg,
             target_kg = excluded.target_kg, height_cm = excluded.height_cm,
             age = excluded.age, sex = excluded.sex, activity = excluded.activity""",
        (weight, weight, target, height, age, sex, activity),
    )
    await db.commit()


async def get_norms(db: Db) -> Norms | None:
    p = await get_profile(db)
    if not p:
        return None
    return calc_norms(
        p["weight_kg"], p["height_cm"], p["age"], p["sex"], p["activity"], p["target_kg"]
    )


async def get_settings(db: Db):
    return await _one(db, "SELECT * FROM settings WHERE id = 1")


async def set_summary_times(db: Db, morning: str, evening: str) -> None:
    await db.execute(
        "UPDATE settings SET morning_time = ?, evening_time = ? WHERE id = 1",
        (morning, evening),
    )
    await db.commit()


async def set_autocarry(db: Db, enabled: bool) -> None:
    await db.execute("UPDATE settings SET autocarry = ? WHERE id = 1", (int(enabled),))
    await db.commit()


async def mark_summary_sent(db: Db, column: str, day: date) -> None:
    if column not in ("last_morning", "last_evening"):
        raise ValueError(column)
    await db.execute(f"UPDATE settings SET {column} = ? WHERE id = 1", (day.isoformat(),))
    await db.commit()


# --- Еда, вода, вес, активность ---

async def add_meal(
    db: Db, day: date, name: str, grams: float | None,
    kcal: float, protein: float, fat: float, carbs: float,
) -> None:
    await db.execute(
        "INSERT INTO meals (day, name, grams, kcal, protein, fat, carbs) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (day.isoformat(), name, grams, kcal, protein, fat, carbs),
    )
    await db.commit()


async def day_totals(db: Db, day: date):
    return await _one(
        db,
        """SELECT COALESCE(SUM(kcal), 0) kcal, COALESCE(SUM(protein), 0) protein,
                  COALESCE(SUM(fat), 0) fat, COALESCE(SUM(carbs), 0) carbs
           FROM meals WHERE day = ?""",
        day.isoformat(),
    )


async def add_water(db: Db, day: date, ml: int) -> None:
    await db.execute("INSERT INTO water (day, ml) VALUES (?, ?)", (day.isoformat(), ml))
    await db.commit()


async def undo_water(db: Db, day: date) -> int | None:
    row = await _one(
        db, "SELECT id, ml FROM water WHERE day = ? ORDER BY id DESC LIMIT 1", day.isoformat()
    )
    if not row:
        return None
    await db.execute("DELETE FROM water WHERE id = ?", (row["id"],))
    await db.commit()
    return row["ml"]


async def water_total(db: Db, day: date) -> int:
    row = await _one(
        db, "SELECT COALESCE(SUM(ml), 0) total FROM water WHERE day = ?", day.isoformat()
    )
    return row["total"]


async def add_weight(
    db: Db, day: date, kg: float, fat_pct: float | None = None, muscle_kg: float | None = None
) -> None:
    """Записывает вес и обновляет профиль: нормы считаются от текущего веса."""
    await db.execute(
        "INSERT INTO weights (day, kg, fat_pct, muscle_kg) VALUES (?, ?, ?, ?)",
        (day.isoformat(), kg, fat_pct, muscle_kg),
    )
    await db.execute("UPDATE profile SET weight_kg = ? WHERE id = 1", (kg,))
    await db.commit()


async def weight_points(db: Db, since: date) -> list[tuple[date, float]]:
    rows = await _all(
        db, "SELECT day, kg FROM weights WHERE day >= ? ORDER BY day, id", since.isoformat()
    )
    return [(date.fromisoformat(r["day"]), r["kg"]) for r in rows]


async def save_activity(
    db: Db, day: date, steps: float | None, active_kcal: float | None, workouts: str | None
) -> None:
    """Скриншот с часов показывает итог дня, поэтому значения заменяются, а не суммируются."""
    await db.execute(
        """INSERT INTO activity (day, steps, active_kcal, workouts) VALUES (?, ?, ?, ?)
           ON CONFLICT (day) DO UPDATE SET
             steps = COALESCE(excluded.steps, steps),
             active_kcal = COALESCE(excluded.active_kcal, active_kcal),
             workouts = COALESCE(excluded.workouts, workouts)""",
        (day.isoformat(), steps, active_kcal, workouts),
    )
    await db.commit()


async def get_activity(db: Db, day: date):
    return await _one(db, "SELECT * FROM activity WHERE day = ?", day.isoformat())


# --- Задачи ---

async def add_task(db: Db, title: str, when: When) -> int:
    cursor = await db.execute(
        "INSERT INTO tasks (title, kind, date, weekdays) VALUES (?, ?, ?, ?)",
        (title, when.kind, when.date.isoformat() if when.date else None, when.weekdays),
    )
    await db.commit()
    return cursor.lastrowid


async def tasks_for_day(db: Db, day: date) -> list:
    rows = await _all(
        db,
        """SELECT t.*, l.status FROM tasks t
           LEFT JOIN task_log l ON l.task_id = t.id AND l.day = ?
           WHERE t.active = 1 ORDER BY t.id""",
        day.isoformat(),
    )
    weekday = str(day.weekday())
    result = []
    for task in rows:
        if task["kind"] == "daily":
            result.append(task)
        elif task["kind"] == "weekly" and weekday in task["weekdays"].split(","):
            result.append(task)
        elif task["kind"] == "once" and task["date"] == day.isoformat():
            result.append(task)
    return result


async def set_task_status(db: Db, task_id: int, day: date, status: str) -> None:
    await db.execute(
        """INSERT INTO task_log (task_id, day, status) VALUES (?, ?, ?)
           ON CONFLICT (task_id, day) DO UPDATE SET status = excluded.status""",
        (task_id, day.isoformat(), status),
    )
    await db.commit()


async def delete_task(db: Db, task_id: int) -> None:
    await db.execute("UPDATE tasks SET active = 0 WHERE id = ?", (task_id,))
    await db.commit()


async def carry_over_tasks(db: Db, today: date) -> int:
    """Переносит на сегодня единичные задачи из прошлого, которые не выполнены."""
    cursor = await db.execute(
        """UPDATE tasks SET date = ?
           WHERE kind = 'once' AND active = 1 AND date < ?
             AND NOT EXISTS (
               SELECT 1 FROM task_log l
               WHERE l.task_id = tasks.id AND l.day = tasks.date AND l.status = 'done'
             )""",
        (today.isoformat(), today.isoformat()),
    )
    await db.commit()
    return cursor.rowcount


# --- Таблетки ---

async def add_pill(
    db: Db, name: str, dose: str, per_dose: float, stock: float | None,
    times: list[str], weekdays: str, now_ts: int,
) -> int:
    cursor = await db.execute(
        "INSERT INTO pills (name, dose, per_dose, stock) VALUES (?, ?, ?, ?)",
        (name, dose, per_dose, stock),
    )
    pill_id = cursor.lastrowid
    for time in times:
        await db.execute(
            "INSERT INTO alarms (kind, pill_id, time, weekdays, created_at) "
            "VALUES ('pill', ?, ?, ?, ?)",
            (pill_id, time, weekdays, now_ts),
        )
    await db.commit()
    return pill_id


async def get_pill(db: Db, pill_id: int):
    return await _one(db, "SELECT * FROM pills WHERE id = ?", pill_id)


async def list_pills(db: Db) -> list:
    return await _all(db, "SELECT * FROM pills WHERE active = 1 ORDER BY id")


async def pill_alarms(db: Db, pill_id: int) -> list:
    return await _all(
        db, "SELECT * FROM alarms WHERE pill_id = ? AND active = 1 ORDER BY time", pill_id
    )


async def delete_pill(db: Db, pill_id: int) -> None:
    """Журнал приёмов остаётся, отключается только расписание."""
    await db.execute("UPDATE pills SET active = 0 WHERE id = ?", (pill_id,))
    await db.execute("UPDATE alarms SET active = 0 WHERE pill_id = ?", (pill_id,))
    await db.execute(
        """UPDATE alarm_events SET status = 'cancelled', next_at = NULL
           WHERE status = 'pending'
             AND alarm_id IN (SELECT id FROM alarms WHERE pill_id = ?)""",
        (pill_id,),
    )
    await db.commit()


async def refill_pill(db: Db, pill_id: int, amount: float) -> float:
    await db.execute(
        "UPDATE pills SET stock = COALESCE(stock, 0) + ? WHERE id = ?", (amount, pill_id)
    )
    await db.commit()
    return (await get_pill(db, pill_id))["stock"]


async def pill_days_left(db: Db, pill) -> float | None:
    """На сколько дней хватит остатка при текущем расписании."""
    if pill["stock"] is None:
        return None
    alarms = await pill_alarms(db, pill["id"])
    per_day = sum(
        pill["per_dose"] * (len(a["weekdays"].split(",")) if a["weekdays"] else 7) / 7
        for a in alarms
    )
    return pill["stock"] / per_day if per_day else None


async def pill_events_for_day(db: Db, day: date) -> list:
    return await _all(
        db,
        """SELECT e.*, a.time, a.pill_id, p.name, p.dose FROM alarm_events e
           JOIN alarms a ON a.id = e.alarm_id JOIN pills p ON p.id = a.pill_id
           WHERE e.day = ? AND a.kind = 'pill' AND e.status != 'cancelled'
           ORDER BY a.time""",
        day.isoformat(),
    )


async def pill_journal(db: Db, since: date) -> list:
    return await _all(
        db,
        """SELECT e.day, e.status, e.resolved_at, a.time, p.name, p.dose FROM alarm_events e
           JOIN alarms a ON a.id = e.alarm_id JOIN pills p ON p.id = a.pill_id
           WHERE e.day >= ? AND a.kind = 'pill' AND e.status != 'cancelled'
           ORDER BY e.day DESC, a.time DESC""",
        since.isoformat(),
    )


# --- Напоминания и срабатывания ---

async def add_reminder(db: Db, text: str, time: str, when: When, now_ts: int) -> int:
    weekdays = when.weekdays
    cursor = await db.execute(
        "INSERT INTO alarms (kind, text, time, weekdays, date, created_at) "
        "VALUES ('reminder', ?, ?, ?, ?, ?)",
        (text, time, weekdays, when.date.isoformat() if when.date else None, now_ts),
    )
    await db.commit()
    return cursor.lastrowid


async def list_reminders(db: Db, today: date) -> list:
    return await _all(
        db,
        """SELECT * FROM alarms
           WHERE kind = 'reminder' AND active = 1 AND (date IS NULL OR date >= ?)
           ORDER BY date IS NOT NULL, date, time""",
        today.isoformat(),
    )


async def delete_reminder(db: Db, alarm_id: int) -> None:
    await db.execute(
        "UPDATE alarms SET active = 0 WHERE id = ? AND kind = 'reminder'", (alarm_id,)
    )
    await db.execute(
        """UPDATE alarm_events SET status = 'cancelled', next_at = NULL
           WHERE alarm_id = ? AND status = 'pending'""",
        (alarm_id,),
    )
    await db.commit()


async def active_alarms(db: Db) -> list:
    return await _all(db, "SELECT * FROM alarms WHERE active = 1")


async def create_event(db: Db, alarm_id: int, day: date, now_ts: int) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO alarm_events (alarm_id, day, next_at) VALUES (?, ?, ?)",
        (alarm_id, day.isoformat(), now_ts),
    )
    await db.commit()


async def due_events(db: Db, now_ts: int) -> list:
    return await _all(
        db,
        """SELECT e.*, a.kind, a.text, a.time, a.pill_id, p.name, p.dose
           FROM alarm_events e
           JOIN alarms a ON a.id = e.alarm_id
           LEFT JOIN pills p ON p.id = a.pill_id
           WHERE e.status = 'pending' AND e.next_at IS NOT NULL AND e.next_at <= ?
           ORDER BY e.next_at""",
        now_ts,
    )


async def get_event(db: Db, event_id: int):
    return await _one(
        db,
        """SELECT e.*, a.kind, a.text, a.time, a.pill_id, p.name, p.dose, p.per_dose
           FROM alarm_events e
           JOIN alarms a ON a.id = e.alarm_id
           LEFT JOIN pills p ON p.id = a.pill_id
           WHERE e.id = ?""",
        event_id,
    )


async def event_sent(
    db: Db, event_id: int, pings: int, next_at: int | None, message_id: int
) -> None:
    await db.execute(
        "UPDATE alarm_events SET pings = ?, next_at = ?, message_id = ? WHERE id = ?",
        (pings, next_at, message_id, event_id),
    )
    await db.commit()


async def mark_missed(db: Db, event_id: int, now_ts: int) -> None:
    await db.execute(
        "UPDATE alarm_events SET status = 'missed', next_at = NULL, resolved_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (now_ts, event_id),
    )
    await db.commit()


async def finish_event(db: Db, event_id: int, status: str, now_ts: int) -> bool:
    """Закрывает срабатывание. False значит, что оно уже закрыто: кнопку нажали повторно.

    Условие в WHERE защищает остаток от двойного списания.
    """
    cursor = await db.execute(
        """UPDATE alarm_events SET status = ?, next_at = NULL, resolved_at = ?
           WHERE id = ? AND status IN ('pending', 'missed')""",
        (status, now_ts, event_id),
    )
    if cursor.rowcount == 0:
        await db.rollback()
        return False
    if status == "done":
        await db.execute(
            """UPDATE pills SET stock = MAX(stock - per_dose, 0)
               WHERE stock IS NOT NULL AND id = (
                 SELECT a.pill_id FROM alarm_events e JOIN alarms a ON a.id = e.alarm_id
                 WHERE e.id = ?
               )""",
            (event_id,),
        )
    await db.commit()
    return True


async def undo_event(db: Db, event_id: int) -> bool:
    """Отменяет ошибочную отметку и возвращает таблетки в остаток."""
    cursor = await db.execute(
        """UPDATE alarm_events SET status = 'pending', next_at = NULL, resolved_at = NULL
           WHERE id = ? AND status IN ('done', 'skipped')""",
        (event_id,),
    )
    if cursor.rowcount == 0:
        await db.rollback()
        return False
    await db.commit()
    return True


async def restore_stock(db: Db, pill_id: int, per_dose: float) -> None:
    await db.execute(
        "UPDATE pills SET stock = stock + ? WHERE id = ? AND stock IS NOT NULL",
        (per_dose, pill_id),
    )
    await db.commit()


async def snooze_event(db: Db, event_id: int, next_at: int) -> bool:
    cursor = await db.execute(
        """UPDATE alarm_events SET status = 'pending', next_at = ?, pings = 0,
           resolved_at = NULL WHERE id = ? AND status IN ('pending', 'missed')""",
        (next_at, event_id),
    )
    await db.commit()
    return cursor.rowcount > 0


def journal_since(today: date, days: int) -> date:
    return today - timedelta(days=days - 1)
