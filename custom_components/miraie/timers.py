"""The AC's own on/off timers (the MirAIe `actm` command).

The timers run on the AC itself, the same ones the MirAIe app sets, so they fire
even if Home Assistant or the internet is down when the time comes.

- Command, on `<topic>/control`: {"actm": [secondsUntilOff, secondsUntilOn], ...}.
  Each slot is the number of seconds from now, or -1 for no timer. Both slots are
  always sent together, so changing one resends the other's remaining time.
- Status, on `<topic>/status` and the HTTP status: "actm": [offEpoch, onEpoch],
  as Unix times, or -1 when unset.

miraie-ac does not handle `actm`, so this module reads it from the raw status and
publishes the command on the library's MQTT client itself, leaving the library as is.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from typing import Any

NO_TIMER = -1
OFF_SLOT = 0
ON_SLOT = 1


def next_occurrence(target: time, now: datetime) -> datetime:
    """The next time the clock shows `target`, tomorrow if it has passed today."""
    candidate = now.replace(
        hour=target.hour, minute=target.minute, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def seconds_until(fires_at: datetime | None, now: datetime) -> int:
    """Seconds from now until `fires_at`, or -1 for none or a time already past."""
    if fires_at is None:
        return NO_TIMER
    seconds = round((fires_at - now).total_seconds())
    return seconds if seconds > 0 else NO_TIMER


def parse_status_slots(value: Any) -> list[datetime | None] | None:
    """Reads the status `actm` ([offEpoch, onEpoch]). None if it is missing or malformed."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    slots: list[datetime | None] = []
    for item in value:
        try:
            epoch = float(item)
        except (TypeError, ValueError):
            epoch = NO_TIMER
        slots.append(
            datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch > 0 else None
        )
    return slots


def build_payload(off_seconds: int, on_seconds: int) -> dict[str, Any]:
    """The control message the MirAIe app sends for timers."""
    return {"actm": [off_seconds, on_seconds], "sid": "1", "cnt": "an"}


class MirAIeTimers:
    """The off and on timer of one AC."""

    def __init__(self, device: Any) -> None:
        self.device = device
        self._fires_at: list[datetime | None] = [None, None]
        self._callbacks: set[Callable[[], None]] = set()

    def register_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.discard(callback)

    def _notify(self) -> None:
        for callback in list(self._callbacks):
            callback()

    def get(self, slot: int, now: datetime) -> datetime | None:
        """When the timer in `slot` fires, or None if it is unset or already past."""
        fires_at = self._fires_at[slot]
        return fires_at if fires_at is not None and fires_at > now else None

    def update_from_status(self, status: Any) -> None:
        """Takes the timers from a status message. Never raises."""
        if not isinstance(status, dict):
            return
        slots = parse_status_slots(status.get("actm"))
        if slots is not None and slots != self._fires_at:
            self._fires_at = slots
            self._notify()

    async def set(self, slot: int, fires_at: datetime | None, now: datetime) -> None:
        """Sets (or with None, cancels) one timer and keeps the other as it is."""
        slots = [self.get(OFF_SLOT, now), self.get(ON_SLOT, now)]
        slots[slot] = fires_at
        payload = build_payload(
            seconds_until(slots[OFF_SLOT], now), seconds_until(slots[ON_SLOT], now)
        )
        client = getattr(self.device.broker, "client", None)
        if client is None:
            raise ConnectionError("Not connected to MirAIe yet")
        await client.publish(self.device.control_topic, json.dumps(payload))
        # Show the change straight away; the AC's next status confirms it.
        self._fires_at = slots
        self._notify()


def hook_status(timers: MirAIeTimers) -> None:
    """Routes the device's MQTT status through `timers` before miraie-ac handles it."""
    device = timers.device
    broker = device.broker
    original = broker.status_callbacks.get(device.status_topic)

    def handler(status: Any) -> None:
        timers.update_from_status(status)
        if original is not None:
            original(status)

    broker.register_device_callback(device.status_topic, handler)


async def async_fetch_status(session: Any, status_url: str, access_token: str, timers: MirAIeTimers) -> None:
    """Reads the timers already set on the AC, from the HTTP status, at start-up."""
    url = status_url.replace("{deviceId}", timers.device.id)
    headers = {"Authorization": f"Bearer {access_token}"}
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        timers.update_from_status(await response.json())


def timers_key(entry_id: str) -> str:
    """Where an entry's timers are kept in hass.data[DOMAIN]."""
    return f"{entry_id}_timers"
