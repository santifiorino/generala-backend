from datetime import datetime, timedelta


def adjust_datetime(dt: datetime) -> datetime:
    """Subtracts 3 hours from a datetime object."""
    # The previous generalas servidas have 00:00 but the right date
    if dt < datetime(2025, 6, 17):
        return dt
    return dt - timedelta(hours=3) 