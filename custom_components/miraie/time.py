"""Off timer and On timer of the MirAIe AC, as time entities.

Setting a time schedules the AC's own timer for the next time the clock shows it
(today, or tomorrow if that time has passed). The state is unknown when no timer is set.
"""

from __future__ import annotations

from datetime import time

from miraie_ac import Device as MirAIeDevice

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .logger import LOGGER
from .timers import OFF_SLOT, ON_SLOT, MirAIeTimers, next_occurrence, timers_key


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the timer entities."""
    all_timers: dict[str, MirAIeTimers] = hass.data[DOMAIN][timers_key(entry.entry_id)]
    entities = []
    for timers in all_timers.values():
        entities += [
            MirAIeTimerTime(timers, OFF_SLOT),
            MirAIeTimerTime(timers, ON_SLOT),
        ]
    async_add_entities(entities)


class MirAIeTimerTime(TimeEntity):
    """When the AC's off (or on) timer fires."""

    def __init__(self, timers: MirAIeTimers, slot: int) -> None:
        self.timers = timers
        self.slot = slot
        self.device: MirAIeDevice = timers.device
        kind = "off" if slot == OFF_SLOT else "on"
        self._attr_should_poll = False
        self._attr_name = f"{self.device.friendly_name} {kind.capitalize()} timer"
        self._attr_unique_id = f"{self.device.id}_{kind}_timer"
        self._attr_icon = "mdi:timer-off-outline" if slot == OFF_SLOT else "mdi:timer-outline"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(identifiers={(DOMAIN, self.device.id)})

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device.status.is_online

    @property
    def native_value(self) -> time | None:
        """The clock time the timer fires at, or None when it is unset."""
        fires_at = self.timers.get(self.slot, dt_util.utcnow())
        if fires_at is None:
            return None
        return dt_util.as_local(fires_at).time().replace(second=0, microsecond=0)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """The full date and time, since the timer may fire tomorrow."""
        fires_at = self.timers.get(self.slot, dt_util.utcnow())
        return {"fires_at": dt_util.as_local(fires_at).isoformat() if fires_at else None}

    async def async_set_value(self, value: time) -> None:
        """Schedule the timer for the next time the clock shows `value`."""
        now = dt_util.now()
        fires_at = next_occurrence(value, now)
        LOGGER.debug(f"Set {self.name} to {fires_at}")
        try:
            await self.timers.set(self.slot, fires_at, now)
        except Exception as error:
            raise HomeAssistantError(f"Could not set {self.name}: {error}") from error

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.timers.register_callback(self.async_write_ha_state)
        self.device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.timers.remove_callback(self.async_write_ha_state)
        self.device.remove_callback(self.async_write_ha_state)
