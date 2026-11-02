"""Разбор текста от пользователя. Чистые функции, поэтому их легко тестировать."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_DAY_NAMES = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2, "четверг": 3,
    "пятница": 4, "пятницу": 4, "суббота": 5, "субботу": 5, "воскресенье": 6,
}
_DAY_NAMES.update({name: i for i, name in enumerate(WEEKDAYS)})


@dataclass(frozen=True)
class When:
    kind: str  # once, daily или weekly
    date: date | None = None
    weekdays: str = ""


def parse_number(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def parse_water(text: str) -> int | None:
    """'+300', '+300 мл', '300 мл', '0,5 л' -> миллилитры."""
    match = re.fullmatch(
        r"(\+)?\s*(\d+(?:[.,]\d+)?)\s*(мл|ml|л|l)?\.?", text.strip().lower()
    )
    if not match or not (match[1] or match[3]):
        return None
    ml = float(match[2].replace(",", "."))
    if match[3] in ("л", "l"):
        ml *= 1000
    return round(ml) if 0 < ml <= 5000 else None


def parse_weight(text: str) -> float | None:
    match = re.fullmatch(r"вес\s*:?\s*(\d+(?:[.,]\d+)?)\s*(кг)?", text.strip().lower())
    if not match:
        return None
    kg = float(match[1].replace(",", "."))
    return kg if 20 <= kg <= 400 else None


def parse_time(text: str) -> str | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    return f"{int(match[1]):02d}:{match[2]}"


def parse_times(text: str) -> list[str] | None:
    parts = [p for p in re.split(r"[,\s]+", text.strip()) if p]
    times = [parse_time(p) for p in parts]
    if not times or None in times:
        return None
    return sorted(set(times))


def parse_course_days(text: str) -> int | None:
    """Длительность курса в днях, от 1 до 10 лет."""
    text = text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 3650:
        return None
    return int(text)


def course_end(days: int, today: date, times: list[str], current_time: str) -> date:
    """Последний день курса. Сегодня считается, только если приём ещё впереди."""
    first_day = today if any(t > current_time for t in times) else today + timedelta(days=1)
    return first_day + timedelta(days=days - 1)


def parse_weekdays(text: str) -> str | None:
    """'пн, ср пт' -> '0,2,4'."""
    parts = [p for p in re.split(r"[,\s]+", text.strip().lower()) if p]
    if not parts or any(p not in _DAY_NAMES for p in parts):
        return None
    return ",".join(str(d) for d in sorted({_DAY_NAMES[p] for p in parts}))


def weekdays_label(weekdays: str) -> str:
    if not weekdays:
        return "каждый день"
    return ", ".join(WEEKDAYS[int(d)] for d in weekdays.split(","))


def parse_date(text: str, today: date) -> date | None:
    """'12.10' или '12.10.2027'. Дата без года не уходит в прошлое."""
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?", text.strip())
    if not match:
        return None
    day, month = int(match[1]), int(match[2])
    try:
        if match[3]:
            return date(int(match[3]), month, day)
        result = date(today.year, month, day)
        return result if result >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def parse_when(text: str, today: date) -> When | None:
    text = re.sub(r"\s+", " ", text.strip().lower())
    if text == "сегодня":
        return When("once", today)
    if text == "завтра":
        return When("once", today + timedelta(days=1))
    if text == "послезавтра":
        return When("once", today + timedelta(days=2))
    if text in ("каждый день", "ежедневно"):
        return When("daily")

    every = re.fullmatch(r"(?:кажд(?:ый|ую|ое|ая))\s+(.+)", text)
    if every:
        days = parse_weekdays(every[1])
        return When("weekly", weekdays=days) if days else None

    days = parse_weekdays(text)
    if days and "," in days:
        return When("weekly", weekdays=days)
    if days:  # один день недели: ближайший, включая сегодня
        ahead = (int(days) - today.weekday()) % 7
        return When("once", today + timedelta(days=ahead))

    exact = parse_date(text, today)
    return When("once", exact) if exact else None


def parse_task(text: str, today: date) -> tuple[When, str] | None:
    """'чт: забрать посылку' -> когда и что."""
    prefix, separator, title = text.partition(":")
    title = title.strip()
    if not separator or not title:
        return None
    when = parse_when(prefix, today)
    return (when, title[:200]) if when else None


def parse_remind(text: str, today: date) -> tuple[When, str, str] | None:
    """'[когда] 18:30 текст' -> когда, время, текст."""
    match = re.fullmatch(r"(?:(.+?)\s+)?(\d{1,2}:\d{2})\s+(.+)", text.strip(), re.S)
    if not match:
        return None
    time = parse_time(match[2])
    when = parse_when(match[1], today) if match[1] else When("daily")
    return (when, time, match[3].strip()[:300]) if time and when else None


def parse_meal(text: str) -> dict | None:
    """'Гречка; 350; 20; 8; 60' -> название, ккал и необязательные БЖУ."""
    parts = [p.strip() for p in text.split(";")]
    if len(parts) not in (2, 5) or not parts[0]:
        return None
    numbers = [parse_number(p) for p in parts[1:]]
    if None in numbers or any(n < 0 for n in numbers):
        return None
    protein, fat, carbs = numbers[1:] if len(numbers) == 4 else (0, 0, 0)
    return {
        "name": parts[0][:100], "grams": None, "kcal": numbers[0],
        "protein": protein, "fat": fat, "carbs": carbs,
    }


def parse_corrections(text: str, aliases: dict[str, str]) -> dict[str, float | str]:
    """'ккал 350, белки 20' -> {'kcal': 350.0, 'protein': 20.0}."""
    result: dict[str, float | str] = {}
    for chunk in re.split(r"[,;\n]+(?!\d)", text):
        match = re.fullmatch(r"\s*([^\d\s:=]+)\s*[:=]?\s*(.+?)\s*", chunk)
        if not match or match[1].lower() not in aliases:
            continue
        key = aliases[match[1].lower()]
        if key in ("name", "workouts"):
            result[key] = match[2][:100]
            continue
        number = parse_number(match[2])
        if number is not None and number >= 0:
            result[key] = number
    return result
