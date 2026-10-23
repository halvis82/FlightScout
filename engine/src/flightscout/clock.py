"""Today's date for the "is it in the past" checks, in one place: the offline
tests pin it, because the saved airline answers they parse have fixed dates."""

from datetime import date


def today() -> date:
    return date.today()
