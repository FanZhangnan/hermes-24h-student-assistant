#!/usr/bin/env python3
"""从本地课表确定性生成课前提醒；空输出代表本次无需推送。"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


LIB = pathlib.Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

from study_assistant.paths import RuntimePaths  # noqa: E402
from study_assistant.repository import Repository  # noqa: E402


ROOT = pathlib.Path(__file__).resolve().parents[1]
ICS_PATH = ROOT / "data" / "calendar" / "timetable.ics"
URL_PATH = ROOT / "data" / "calendar" / "timetable_ics_url.txt"
STATE_PATH = ROOT / "data" / "calendar" / "reminder_state.json"
TIMEZONE = "UTC"


def _load_state():
    if not STATE_PATH.is_file():
        return {"sent": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sent": {}}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _refresh_ics():
    if not URL_PATH.is_file():
        return
    url = URL_PATH.read_text(encoding="utf-8").strip()
    if not url.startswith("https://"):
        return
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = response.read()
        if data and b"BEGIN:VCALENDAR" in data:
            ICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            ICS_PATH.write_bytes(data)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        pass


def _unfold(raw):
    lines = []
    for line in raw.splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _parse_events(raw):
    events = []
    current = None
    for line in _unfold(raw):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0]] = value
    return events


def _parse_datetime(value, timezone):
    value = value.strip()
    if value.endswith("Z"):
        utc = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=ZoneInfo("UTC")
        )
        return utc.astimezone(timezone)
    if "T" in value:
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(
            tzinfo=timezone
        )
    return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone)


def _in_quiet_hours(now, quiet_start, quiet_end):
    start_hour, start_minute = (int(value) for value in quiet_start.split(":"))
    end_hour, end_minute = (int(value) for value in quiet_end.split(":"))
    current = now.hour * 60 + now.minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _policy(repository):
    default = {
        "lead_minutes": 30,
        "quiet_start": "22:30",
        "quiet_end": "07:00",
        "enabled": 1,
    }
    if not repository.database.is_file():
        return default
    return repository.get_policy("class") or default


def main(now=None):
    paths = RuntimePaths.from_environment()
    policy = _policy(Repository(paths.database))
    if not policy.get("enabled", 1):
        return 0

    timezone = ZoneInfo(TIMEZONE)
    now = now or datetime.now(timezone)
    if _in_quiet_hours(now, policy["quiet_start"], policy["quiet_end"]):
        return 0

    _refresh_ics()
    if not ICS_PATH.is_file():
        return 0
    raw = ICS_PATH.read_text(encoding="utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in raw:
        return 0

    state = _load_state()
    sent = state.setdefault("sent", {})
    cutoff = (now - timedelta(days=14)).isoformat()
    sent = {key: value for key, value in sent.items() if value >= cutoff}
    state["sent"] = sent
    window_end = now + timedelta(minutes=int(policy["lead_minutes"]))

    due = []
    for event in _parse_events(raw):
        start_raw = event.get("DTSTART")
        if not start_raw or "T" not in start_raw:
            continue
        try:
            start = _parse_datetime(start_raw, timezone)
            end_raw = event.get("DTEND")
            end = _parse_datetime(end_raw, timezone) if end_raw and "T" in end_raw else None
        except ValueError:
            continue
        if not now <= start <= window_end:
            continue
        uid = event.get("UID") or "{}|{}".format(
            start.isoformat(), event.get("SUMMARY", "")
        )
        key = "{}|{}".format(uid, start.isoformat())
        if key not in sent:
            due.append((start, end, event, key))

    if not due:
        _save_state(state)
        return 0

    due.sort(key=lambda item: item[0])
    lines = ["【课前提醒｜提前 {} 分钟】".format(policy["lead_minutes"])]
    for start, end, event, key in due:
        summary = event.get("SUMMARY", "课程").replace("\\,", ",").strip()
        location = (event.get("LOCATION") or "地点未标注").strip()
        if location == "-":
            location = "地点未标注"
        period = start.strftime("%H:%M")
        if end is not None:
            period = "{}-{}".format(period, end.strftime("%H:%M"))
        lines.append("- {}｜{}｜{}".format(summary, period, location))
        sent[key] = now.isoformat()

    _save_state(state)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
