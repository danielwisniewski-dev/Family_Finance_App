"""Household calendar date, independent of the cloud server's UTC clock."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def household_today() -> date:
    name = os.environ.get("FF_TIMEZONE", "America/New_York" if os.environ.get("FF_MODE") == "hosted" else "")
    return datetime.now(ZoneInfo(name)).date() if name else date.today()
