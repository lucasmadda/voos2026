from datetime import date, datetime, timezone

from voos.tz import brasilia_naive_to_utc, hhmm_near, local_day, local_naive_to_utc, parse_vra_datetime, utc_to_local


def test_vra_brasilia_to_utc():
    assert parse_vra_datetime("24/10/2026 10:30") == datetime(2026, 10, 24, 13, 30, tzinfo=timezone.utc)
    assert parse_vra_datetime("") is None
    # Manaus (UTC-4) é registrado em Brasília no VRA: 00:00 Brasília = 03:00Z
    assert brasilia_naive_to_utc(datetime(2026, 10, 24, 0, 0)) == datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)


def test_local_to_utc_by_airport():
    assert local_naive_to_utc(datetime(2026, 10, 24, 10, 30), "SBPA") == datetime(2026, 10, 24, 13, 30, tzinfo=timezone.utc)
    # Noronha é UTC-2
    assert local_naive_to_utc(datetime(2026, 10, 24, 10, 30), "SBFN") == datetime(2026, 10, 24, 12, 30, tzinfo=timezone.utc)
    assert local_day(datetime(2026, 10, 25, 2, 59, tzinfo=timezone.utc), "SBPA") == date(2026, 10, 24)
    assert local_day(datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc), "SBPA") == date(2026, 10, 25)
    assert utc_to_local(datetime(2026, 10, 24, 13, 30, tzinfo=timezone.utc), "SBPA").hour == 10


def test_hhmm_rollover():
    base = datetime(2026, 10, 25, 0, 15)
    assert hhmm_near("01:15", base) == datetime(2026, 10, 25, 1, 15)
    late = datetime(2026, 10, 24, 23, 50)
    assert hhmm_near("00:20", late) == datetime(2026, 10, 25, 0, 20)
    early = datetime(2026, 10, 25, 0, 10)
    assert hhmm_near("23:40", early) == datetime(2026, 10, 24, 23, 40)
    assert hhmm_near("", base) is None
    assert hhmm_near("xx", base) is None
