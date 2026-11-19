"""Tests for the AC timers (custom_components/miraie/timers.py, time.py, button.py).

Run with: pip install homeassistant miraie-ac==1.1.2 pytest pytest-asyncio && pytest tests
"""

import json
from datetime import datetime, time, timedelta, timezone

import pytest

from custom_components.miraie.timers import (
    OFF_SLOT,
    ON_SLOT,
    MirAIeTimers,
    build_payload,
    hook_status,
    next_occurrence,
    parse_status_slots,
    seconds_until,
)

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 19, 11, 16, 43, tzinfo=IST)


class FakeClient:
    def __init__(self):
        self.published = []

    async def publish(self, topic, payload):
        self.published.append((topic, json.loads(payload)))


class FakeBroker:
    def __init__(self):
        self.client = FakeClient()
        self.status_callbacks = {}

    def register_device_callback(self, topic, callback):
        self.status_callbacks[topic] = callback


class FakeStatus:
    is_online = True


class FakeDevice:
    id = "abc123"
    friendly_name = "Bedroom"
    control_topic = "home/abc123/control"
    status_topic = "home/abc123/status"

    def __init__(self):
        self.broker = FakeBroker()
        self.status = FakeStatus()


def epoch(dt):
    return int(dt.timestamp())


def test_next_occurrence_today_and_tomorrow():
    assert next_occurrence(time(11, 40), NOW) == NOW.replace(hour=11, minute=40, second=0)
    assert next_occurrence(time(9, 0), NOW) == datetime(2026, 11, 20, 9, 0, tzinfo=IST)
    # The current minute has already started, so it means tomorrow.
    assert next_occurrence(time(11, 16), NOW).day == 20


def test_seconds_until():
    assert seconds_until(None, NOW) == -1
    assert seconds_until(NOW - timedelta(seconds=5), NOW) == -1
    assert seconds_until(NOW.replace(hour=11, minute=40, second=0), NOW) == 1397


def test_parse_status_slots():
    off = datetime(2026, 11, 19, 12, 20, tzinfo=IST)
    assert parse_status_slots([epoch(off), -1]) == [off, None]
    assert parse_status_slots(["-1", str(epoch(off))]) == [None, off]
    assert parse_status_slots([None, "x"]) == [None, None]
    assert parse_status_slots(None) is None
    assert parse_status_slots([1]) is None


def test_payload_order_is_off_then_on():
    assert build_payload(3830, 1386) == {"actm": [3830, 1386], "sid": "1", "cnt": "an"}


@pytest.mark.asyncio
async def test_set_keeps_the_other_timer_and_cancel():
    device = FakeDevice()
    timers = MirAIeTimers(device)
    on_at = NOW + timedelta(seconds=1430)
    timers.update_from_status({"actm": [-1, epoch(on_at)]})

    await timers.set(OFF_SLOT, NOW + timedelta(seconds=3830), NOW)
    assert device.broker.client.published[-1] == (
        "home/abc123/control",
        {"actm": [3830, 1430], "sid": "1", "cnt": "an"},
    )
    assert timers.get(OFF_SLOT, NOW) == NOW + timedelta(seconds=3830)

    await timers.set(OFF_SLOT, None, NOW)
    assert device.broker.client.published[-1][1]["actm"] == [-1, 1430]
    await timers.set(ON_SLOT, None, NOW)
    assert device.broker.client.published[-1][1]["actm"] == [-1, -1]


@pytest.mark.asyncio
async def test_expired_timer_is_sent_as_none():
    device = FakeDevice()
    timers = MirAIeTimers(device)
    timers.update_from_status({"actm": [epoch(NOW - timedelta(minutes=1)), -1]})
    assert timers.get(OFF_SLOT, NOW) is None
    await timers.set(ON_SLOT, NOW + timedelta(seconds=60), NOW)
    assert device.broker.client.published[-1][1]["actm"] == [-1, 60]


@pytest.mark.asyncio
async def test_not_connected_raises():
    device = FakeDevice()
    del device.broker.client
    with pytest.raises(ConnectionError):
        await MirAIeTimers(device).set(OFF_SLOT, NOW + timedelta(hours=1), NOW)


def test_hook_status_reads_timers_then_calls_library():
    device = FakeDevice()
    seen = []
    device.broker.status_callbacks[device.status_topic] = seen.append
    timers = MirAIeTimers(device)
    changes = []
    timers.register_callback(lambda: changes.append(1))
    hook_status(timers)

    on_at = NOW + timedelta(hours=2)
    status = {"actm": [-1, epoch(on_at)], "ps": "off"}
    device.broker.status_callbacks[device.status_topic](status)
    assert seen == [status]
    assert timers.get(ON_SLOT, NOW) == on_at
    assert changes == [1]
    # The same timers again: no change notification.
    device.broker.status_callbacks[device.status_topic](status)
    assert changes == [1]
    # Junk is ignored rather than raising.
    timers.update_from_status("garbage")
    timers.update_from_status({"actm": "garbage"})
    assert timers.get(ON_SLOT, NOW) == on_at


@pytest.mark.asyncio
async def test_entities(monkeypatch):
    from homeassistant.util import dt as dt_util

    from custom_components.miraie.button import MirAIeCancelTimerButton
    from custom_components.miraie.time import MirAIeTimerTime

    dt_util.set_default_time_zone(IST)
    monkeypatch.setattr(dt_util, "now", lambda time_zone=None: NOW)
    monkeypatch.setattr(dt_util, "utcnow", lambda: NOW.astimezone(timezone.utc))

    device = FakeDevice()
    timers = MirAIeTimers(device)
    off_time = MirAIeTimerTime(timers, OFF_SLOT)
    on_time = MirAIeTimerTime(timers, ON_SLOT)
    cancel_off = MirAIeCancelTimerButton(timers, OFF_SLOT)

    assert off_time.name == "Bedroom Off timer"
    assert off_time.unique_id == "abc123_off_timer"
    assert cancel_off.unique_id == "abc123_cancel_off_timer"
    assert off_time.native_value is None

    await off_time.async_set_value(time(23, 0))
    sent = device.broker.client.published[-1][1]["actm"]
    assert sent == [seconds_until(datetime(2026, 11, 19, 23, 0, tzinfo=IST), NOW), -1]
    assert off_time.native_value == time(23, 0)
    assert off_time.extra_state_attributes["fires_at"] == "2026-11-19T23:00:00+05:30"
    assert on_time.native_value is None

    await cancel_off.async_press()
    assert device.broker.client.published[-1][1]["actm"] == [-1, -1]
    assert off_time.native_value is None
