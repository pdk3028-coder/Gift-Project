"""Application timestamps use Korean standard time, regardless of server locale."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name='KST')


def korea_now():
    # Keep the existing DB/display format; its wall-clock values are always KST.
    return datetime.now(KST).replace(tzinfo=None)
