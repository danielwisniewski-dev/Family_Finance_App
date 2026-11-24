from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import islice


INTERVALS = {"weekly": 7, "every_two_weeks": 14}
LAST_DAY = 0


def day_in_month(day: int, days_in_month: int) -> int:
    return days_in_month if day == LAST_DAY else min(day, days_in_month)


@dataclass(frozen=True)
class PaydayRule:
    frequency: str
    starts_on: date
    day_one: int | None = None
    day_two: int | None = None

    def __post_init__(self):
        first, second = self.day_one, self.day_two
        if self.frequency in INTERVALS:
            if first is None and second is None:
                return
        elif self.frequency == "monthly":
            if first is not None and LAST_DAY <= first <= 31 and second is None:
                return
        elif self.frequency == "twice_monthly":
            if (first is not None and second is not None and LAST_DAY <= first <= 31 and LAST_DAY <= second <= 31
                    and day_in_month(first, 28) != day_in_month(second, 28)):
                return
            raise ValueError("Choose two different days that never overlap, including in February.")
        raise ValueError("Choose a valid frequency and payday days.")

    def dates_from(self, since: date):
        start = max(since, self.starts_on)
        if self.frequency in INTERVALS:
            interval = INTERVALS[self.frequency]
            first = start.toordinal() + (self.starts_on.toordinal() - start.toordinal()) % interval
            yield from (date.fromordinal(day) for day in range(first, date.max.toordinal() + 1, interval))
            return
        year, month = start.year, start.month
        while year <= date.max.year:
            last = calendar.monthrange(year, month)[1]
            days = [day_in_month(day, last) for day in (self.day_one, self.day_two) if day is not None]
            for day in sorted(days):
                candidate = date(year, month, day)
                if candidate >= start:
                    yield candidate
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1

    def includes(self, day: date) -> bool:
        return next(self.dates_from(day), None) == day

    def upcoming(self, since: date, moves: dict[date, date], limit: int):
        regular = islice((day for day in self.dates_from(since) if day not in moves), limit)
        choices = [(day, day) for day in regular]
        choices.extend((shifted, original) for original, shifted in moves.items() if shifted >= since)
        return sorted(choices)[:limit]


def rule_from_row(row):
    return PaydayRule(row["frequency"], date.fromisoformat(row["starts_on"]), row["day_one"], row["day_two"])


def household_schedules(connection, household_id: int, today: date, limit: int = 6):
    schedules = connection.execute(
        "SELECT id, name, frequency, starts_on, day_one, day_two FROM payday_schedules WHERE household_id=? ORDER BY name, id",
        (household_id,),
    ).fetchall()
    moves = defaultdict(dict)
    for move in connection.execute(
        """SELECT m.schedule_id, m.original_date, m.moved_to FROM payday_moves m
           JOIN payday_schedules s ON s.id=m.schedule_id
           WHERE s.household_id=? AND (m.original_date>=? OR m.moved_to>=?)""",
        (household_id, today.isoformat(), today.isoformat()),
    ):
        moves[move["schedule_id"]][date.fromisoformat(move["original_date"])] = date.fromisoformat(move["moved_to"])
    upcoming = [
        {
            "schedule_id": schedule["id"], "name": schedule["name"],
            "payday_date": actual.isoformat(), "original_date": original.isoformat(),
        }
        for schedule in schedules
        for actual, original in rule_from_row(schedule).upcoming(today, moves[schedule["id"]], limit)
    ]
    upcoming.sort(key=lambda item: (item["payday_date"], item["schedule_id"], item["original_date"]))
    return {"today": today.isoformat(), "schedules": [dict(row) for row in schedules], "upcoming_paydays": upcoming}


def next_household_payday(connection, household_id: int, today: date) -> str | None:
    one_time = connection.execute(
        "SELECT MIN(payday_date) FROM paydays WHERE household_id=? AND payday_date>=?",
        (household_id, today.isoformat()),
    ).fetchone()[0]
    upcoming = household_schedules(connection, household_id, today, limit=1)["upcoming_paydays"]
    scheduled = upcoming[0]["payday_date"] if upcoming else None
    return min((value for value in (one_time, scheduled) if value is not None), default=None)


class PaydayScheduleRepositoryMixin:
    def list_payday_schedules(self, household_id: int, today: date):
        with self.connect() as connection:
            connection.execute("BEGIN")
            return household_schedules(connection, household_id, today, limit=3)

    @staticmethod
    def _payday_schedule(connection, household_id, schedule_id):
        row = connection.execute(
            "SELECT * FROM payday_schedules WHERE household_id=? AND id=?", (household_id, schedule_id)
        ).fetchone()
        if row is None:
            raise PermissionError("Payday schedule is unavailable for this household.")
        return row

    def save_payday_schedule(self, household_id: int, name: str, rule: PaydayRule, *,
                             schedule_id: int | None = None, actor_user_id: int | None = None) -> int:
        if not isinstance(name, str) or not (0 < len(name.strip()) <= 80):
            raise ValueError("Enter a schedule name of 1 to 80 characters.")
        name = name.strip()
        values = (name, rule.frequency, rule.starts_on.isoformat(), rule.day_one, rule.day_two)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_household(connection, household_id)
            if schedule_id is not None:
                before = self._payday_schedule(connection, household_id, schedule_id)
                if before["name"] == name and rule_from_row(before) == rule:
                    return schedule_id
            existing = connection.execute(
                "SELECT * FROM payday_schedules WHERE household_id=? AND name=? COLLATE NOCASE",
                (household_id, name),
            ).fetchone()
            if existing is not None and existing["id"] != schedule_id:
                if schedule_id is None and rule_from_row(existing) == rule:
                    return existing["id"]
                raise ValueError("A payday schedule with that name already exists.")
            if schedule_id is None:
                schedule_id = connection.execute(
                    """INSERT INTO payday_schedules(household_id, name, frequency, starts_on, day_one, day_two)
                       VALUES (?, ?, ?, ?, ?, ?)""", (household_id, *values),
                ).lastrowid
                action = "added"
            else:
                connection.execute(
                    """UPDATE payday_schedules SET name=?, frequency=?, starts_on=?, day_one=?, day_two=?
                       WHERE id=?""", (*values, schedule_id),
                )
                moves = connection.execute("SELECT original_date FROM payday_moves WHERE schedule_id=?", (schedule_id,))
                obsolete = [(schedule_id, row[0]) for row in moves if not rule.includes(date.fromisoformat(row[0]))]
                connection.executemany("DELETE FROM payday_moves WHERE schedule_id=? AND original_date=?", obsolete)
                action = "updated"
            self._log_payday_schedule(connection, household_id, schedule_id, actor_user_id,
                                      f"{name} payday schedule was {action}.")
            return schedule_id

    def remove_payday_schedule(self, household_id: int, schedule_id: int, actor_user_id: int):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._payday_schedule(connection, household_id, schedule_id)
            connection.execute("DELETE FROM payday_schedules WHERE id=?", (schedule_id,))
            self._log_payday_schedule(connection, household_id, schedule_id, actor_user_id,
                                      f"{row['name']} payday schedule was removed.")

    def move_scheduled_payday(self, household_id: int, schedule_id: int, original: date,
                              moved_to: date | None, today: date, actor_user_id: int):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._payday_schedule(connection, household_id, schedule_id)
            if not rule_from_row(row).includes(original):
                raise ValueError("That date is no longer part of this schedule.")
            existing = connection.execute(
                "SELECT moved_to FROM payday_moves WHERE schedule_id=? AND original_date=?",
                (schedule_id, original.isoformat()),
            ).fetchone()
            current = date.fromisoformat(existing[0]) if existing else original
            if min(current, moved_to or original) < today:
                raise ValueError("Only upcoming paydays can be moved.")
            if (moved_to or original) == current:
                return
            if moved_to is None or moved_to == original:
                connection.execute(
                    "DELETE FROM payday_moves WHERE schedule_id=? AND original_date=?",
                    (schedule_id, original.isoformat()),
                )
            else:
                connection.execute(
                    """INSERT INTO payday_moves(schedule_id, original_date, moved_to) VALUES (?, ?, ?)
                       ON CONFLICT(schedule_id, original_date) DO UPDATE SET moved_to=excluded.moved_to""",
                    (schedule_id, original.isoformat(), moved_to.isoformat()),
                )
            self._log_payday_schedule(connection, household_id, schedule_id, actor_user_id,
                                      f"{row['name']} payday moved from {current} to {moved_to or original}.")

    def _log_payday_schedule(self, connection, household_id, schedule_id, actor_user_id, message):
        if actor_user_id is not None:
            self._insert_notification_event(
                connection, household_id=household_id, budget_month_id=None, event_type="payday_changed",
                actor_user_id=actor_user_id, affected_entity_type="payday_schedule", affected_entity_id=schedule_id,
                title="Payday changed", message=message, severity="caution",
            )
