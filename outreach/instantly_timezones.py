"""Instantly accepts only its own list of time zone names (not every standard one), so
Europe/London, for example, is refused. This turns any standard time zone into the
Instantly name that keeps exactly the same clock all year (Europe/London -> Europe/Isle_of_Man)."""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import PipelineError

# Instantly API v2, campaign_schedule.schedules[].timezone, in Instantly's own order.
ALLOWED = [
    "Etc/GMT+12", "Etc/GMT+11", "Etc/GMT+10", "America/Anchorage", "America/Dawson", "America/Creston",
    "America/Chihuahua", "America/Boise", "America/Belize", "America/Chicago", "America/Bahia_Banderas",
    "America/Regina", "America/Bogota", "America/Detroit", "America/Indiana/Marengo", "America/Caracas",
    "America/Asuncion", "America/Glace_Bay", "America/Campo_Grande", "America/Anguilla", "America/Santiago",
    "America/St_Johns", "America/Sao_Paulo", "America/Argentina/La_Rioja", "America/Araguaina",
    "America/Godthab", "America/Montevideo", "America/Bahia", "America/Noronha", "America/Scoresbysund",
    "Atlantic/Cape_Verde", "Africa/Casablanca", "America/Danmarkshavn", "Europe/Isle_of_Man",
    "Atlantic/Canary", "Africa/Abidjan", "Arctic/Longyearbyen", "Europe/Belgrade", "Africa/Ceuta",
    "Europe/Sarajevo", "Africa/Algiers", "Africa/Windhoek", "Asia/Nicosia", "Asia/Beirut", "Africa/Cairo",
    "Asia/Damascus", "Europe/Bucharest", "Africa/Blantyre", "Europe/Helsinki", "Europe/Istanbul",
    "Asia/Jerusalem", "Africa/Tripoli", "Asia/Amman", "Asia/Baghdad", "Europe/Kaliningrad", "Asia/Aden",
    "Africa/Addis_Ababa", "Europe/Kirov", "Europe/Astrakhan", "Asia/Tehran", "Asia/Dubai", "Asia/Baku",
    "Indian/Mahe", "Asia/Tbilisi", "Asia/Yerevan", "Asia/Kabul", "Antarctica/Mawson", "Asia/Yekaterinburg",
    "Asia/Karachi", "Asia/Kolkata", "Asia/Colombo", "Asia/Kathmandu", "Antarctica/Vostok", "Asia/Dhaka",
    "Asia/Rangoon", "Antarctica/Davis", "Asia/Novokuznetsk", "Asia/Hong_Kong", "Asia/Krasnoyarsk",
    "Asia/Brunei", "Australia/Perth", "Asia/Taipei", "Asia/Choibalsan", "Asia/Irkutsk", "Asia/Dili",
    "Asia/Pyongyang", "Australia/Adelaide", "Australia/Darwin", "Australia/Brisbane", "Australia/Melbourne",
    "Antarctica/DumontDUrville", "Australia/Currie", "Asia/Chita", "Antarctica/Macquarie", "Asia/Sakhalin",
    "Pacific/Auckland", "Etc/GMT-12", "Pacific/Fiji", "Asia/Anadyr", "Asia/Kamchatka", "Etc/GMT-13",
    "Pacific/Apia",
]
# Preferred matches where several Instantly names keep the same clock.
PREFERRED = {
    "Europe/London": "Europe/Isle_of_Man", "Europe/Dublin": "Europe/Isle_of_Man",
    "Europe/Lisbon": "Europe/Isle_of_Man", "America/New_York": "America/Detroit",
    "Asia/Riyadh": "Asia/Aden", "Asia/Qatar": "Asia/Aden", "Asia/Kuwait": "Asia/Aden",
    "Africa/Nairobi": "Africa/Addis_Ababa", "Africa/Johannesburg": "Africa/Blantyre",
    "Africa/Lagos": "Africa/Algiers", "Asia/Singapore": "Asia/Brunei", "Asia/Shanghai": "Asia/Hong_Kong",
}
CENTRAL_EUROPE = "Europe/Belgrade"


def _offsets(name, year):
    zone = ZoneInfo(name)
    return tuple(dt.datetime(year, m, 15, 12, tzinfo=zone).utcoffset() for m in (1, 4, 7, 10))


def instantly_timezone(name, year=None):
    """The Instantly time zone name with the same clock as `name` all year."""
    if name in ALLOWED:
        return name
    if name in PREFERRED:
        return PREFERRED[name]
    year = year or dt.date.today().year
    try:
        wanted = _offsets(name, year)
    except (ZoneInfoNotFoundError, ValueError):
        raise PipelineError(f'"{name}" in config/settings.yaml (send.schedule) is not a time zone name')
    if _offsets(CENTRAL_EUROPE, year) == wanted:
        return CENTRAL_EUROPE
    for candidate in ALLOWED:
        try:
            if _offsets(candidate, year) == wanted:
                return candidate
        except ZoneInfoNotFoundError:
            continue
    raise PipelineError(
        f'Instantly has no time zone with the same clock as "{name}". Pick another time zone for that '
        "market in config/settings.yaml (send.schedule).")
