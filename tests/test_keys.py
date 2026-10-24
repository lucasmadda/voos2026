from datetime import datetime, timezone

from voos.keys import carrier_group, carrier_icao_from_iata, flight_key, normalize_number, split_fraport_flight


def test_normalize_number():
    assert normalize_number("0904") == ("904", "")
    assert normalize_number("Z9628") == ("9628", "Z")
    assert normalize_number(1979) == ("1979", "")
    assert normalize_number("") == ("", "")
    assert normalize_number("ABC") == ("", "ABC")


def test_flight_key_same_across_sources():
    sched = datetime(2026, 10, 24, 13, 30, tzinfo=timezone.utc)
    k = flight_key("GLO", "1979", "SBPA", sched)
    assert k == "GLO-1979-SBPA-20261024T1330Z"
    assert flight_key("GLO", 1979, "sbpa", sched) == k
    assert flight_key("GLO", "01979", "SBPA", sched) == k


def test_fraport_split_and_crosswalk():
    assert split_fraport_flight("G31979") == ("G3", "1979")
    assert split_fraport_flight("AD4151") == ("AD", "4151")
    assert split_fraport_flight("2Z1234") == ("2Z", "1234")
    assert carrier_icao_from_iata("G3") == "GLO"
    assert carrier_icao_from_iata("ad") == "AZU"
    assert carrier_icao_from_iata("XX") is None
    assert carrier_group("GLO") == "GOL"
    assert carrier_group("TAM") == "LATAM"
    assert carrier_group("ZZZ") == "outras"
