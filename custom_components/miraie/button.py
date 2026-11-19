"""Buttons that cancel the MirAIe AC's off or on timer."""

from __future__ import annotations

from miraie_ac import Device as MirAIeDevice

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .logger import LOGGER
from .timers import OFF_SLOT, ON_SLOT, MirAIeTimers, timers_key


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the cancel-timer buttons."""
    all_timers: dict[str, MirAIeTimers] = hass.data[DOMAIN][timers_key(entry.entry_id)]
    entities = []
    for timers in all_timers.values():
        entities += [
            MirAIeCancelTimerButton(timers, OFF_SLOT),
            MirAIeCancelTimerButton(timers, ON_SLOT),
        ]
    async_add_entities(entities)


class MirAIeCancelTimerButton(ButtonEntity):
    """Cancels the AC's off (or on) timer and keeps the other one."""

    def __init__(self, timers: MirAIeTimers, slot: int) -> None:
        self.timers = timers
        self.slot = slot
        self.device: MirAIeDevice = timers.device
        kind = "off" if slot == OFF_SLOT else "on"
        self._attr_should_poll = False
        self._attr_name = f"{self.device.friendly_name} Cancel {kind} timer"
        self._attr_unique_id = f"{self.device.id}_cancel_{kind}_timer"
        self._attr_icon = "mdi:timer-cancel-outline"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(identifiers={(DOMAIN, self.device.id)})

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device.status.is_online

    async def async_press(self) -> None:
        """Cancel the timer."""
        LOGGER.debug(f"{self.name} pressed")
        try:
            await self.timers.set(self.slot, None, dt_util.utcnow())
        except Exception as error:
            raise HomeAssistantError(f"Could not cancel the timer: {error}") from error

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        self.device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self.device.remove_callback(self.async_write_ha_state)
