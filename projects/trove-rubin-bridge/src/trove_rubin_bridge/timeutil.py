from __future__ import annotations

from datetime import datetime, timedelta, timezone

_MJD_EPOCH = datetime(1858, 11, 17, tzinfo=timezone.utc)


def mjd_to_datetime(mjd: float) -> datetime:
    return _MJD_EPOCH + timedelta(days=float(mjd))
