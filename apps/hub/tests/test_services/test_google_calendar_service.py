import pytest
from hub.services.google_calendar_service import parse_ical_content, _parse_ical_datetime


def test_parse_ical_datetime():
    # Data simples (VALUE=DATE)
    d, h = _parse_ical_datetime("VALUE=DATE:20260513")
    assert d == "2026-05-13"
    assert h == "00:00"

    # Data e hora UTC no verão (agosto: UTC+1 em Portugal)
    d2, h2 = _parse_ical_datetime("20260818T170000Z")
    assert d2 == "2026-08-18"
    assert h2 == "18:00"  # 17:00 UTC + 1h = 18:00 local


def test_parse_ical_content():
    sample_ical = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
BEGIN:VEVENT
DTSTART:20260918T080000Z
DTEND:20260918T090000Z
DTSTAMP:20260826T150000Z
UID:sample-uid-123@google.com
SUMMARY:Atribuição de vagas Tumo
LOCATION:Porto
DESCRIPTION:Abertura das vagas no portal
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260513
DTEND;VALUE=DATE:20260514
UID:sample-uid-456@google.com
SUMMARY:Visita de estudo ao Exploratório
END:VEVENT
END:VCALENDAR
"""
    events = parse_ical_content(sample_ical)
    assert len(events) == 2

    e1 = events[0]
    assert e1["id"] == "google-sample-uid-123@google.com"
    assert e1["titulo"] == "Atribuição de vagas Tumo"
    assert e1["data"] == "2026-09-18"
    assert e1["hora"] == "09:00"  # 08:00Z + 1h
    assert e1["local"] == "Porto"
    assert e1["tipo"] == "google"
    assert e1["cor"] == "sky"

    e2 = events[1]
    assert e2["titulo"] == "Visita de estudo ao Exploratório"
    assert e2["data"] == "2026-05-13"
    assert e2["hora"] == "00:00"
