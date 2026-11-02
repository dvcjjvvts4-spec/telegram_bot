"""Расчёты норм и прогресса. Здесь только чистые функции: без базы и Telegram."""

from dataclasses import dataclass
from datetime import date, timedelta

ACTIVITY_FACTORS = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725, 5: 1.9}
ACTIVITY_LABELS = {
    1: "почти нет движения",
    2: "лёгкая (1–3 тренировки в неделю)",
    3: "средняя (3–5 тренировок)",
    4: "высокая (6–7 тренировок)",
    5: "очень высокая (спорт и физическая работа)",
}
MAINTAIN_ZONE_KG = 1.0  # разница с целью меньше этой считается поддержанием


@dataclass(frozen=True)
class Norms:
    goal: str
    bmr: int
    maintenance: int
    kcal: int
    protein: int
    fat: int
    carbs: int
    water_ml: int
    floored: bool  # норму подняли до базового обмена


def bmr(weight: float, height: float, age: int, sex: str) -> float:
    """Базовый обмен по формуле Миффлина — Сан Жеора."""
    base = 10 * weight + 6.25 * height - 5 * age
    return base + (5 if sex == "m" else -161)


def calc_norms(
    weight: float, height: float, age: int, sex: str, activity: int, target: float
) -> Norms:
    base = bmr(weight, height, age, sex)
    maintenance = base * ACTIVITY_FACTORS[activity]

    if target < weight - MAINTAIN_ZONE_KG:
        goal, factor = "похудение", 0.825  # середина диапазона −15–20%
    elif target > weight + MAINTAIN_ZONE_KG:
        goal, factor = "набор", 1.125  # середина диапазона +10–15%
    else:
        goal, factor = "поддержание", 1.0

    wanted = maintenance * factor
    kcal = max(wanted, base)  # предохранитель: не ниже базового обмена
    protein = 1.8 * weight
    fat = 0.9 * weight
    carbs = max((kcal - protein * 4 - fat * 9) / 4, 0)

    return Norms(
        goal=goal,
        bmr=round(base),
        maintenance=round(maintenance),
        kcal=round(kcal),
        protein=round(protein),
        fat=round(fat),
        carbs=round(carbs),
        water_ml=round(32.5 * weight),
        floored=wanted < base,
    )


def weekly_change(points: list[tuple[date, float]]) -> float | None:
    """Изменение веса в кг за неделю по линейному тренду.

    Нужно минимум 7 дней между первым и последним замером: иначе дневные
    колебания воды в организме выглядят как реальное изменение веса.
    """
    if len(points) < 2:
        return None
    start = min(day for day, _ in points)
    xs = [(day - start).days for day, _ in points]
    ys = [kg for _, kg in points]
    if max(xs) < 7:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    return slope * 7


def too_fast_loss(weekly: float | None, weight: float) -> bool:
    return weekly is not None and weekly < -0.01 * weight


def forecast_date(
    current: float, target: float, weekly: float | None, today: date
) -> date | None:
    """Дата достижения цели, если вес движется к ней."""
    if weekly is None or weekly == 0:
        return None
    weeks = (target - current) / weekly
    if weeks <= 0 or weeks > 520:
        return None
    return today + timedelta(days=round(weeks * 7))


def progress_percent(start: float, current: float, target: float) -> int:
    if start == target:
        return 100
    done = (start - current) / (start - target) * 100
    return max(0, min(100, round(done)))
