"""The mirAIe integration."""
from __future__ import annotations

from miraie_ac import MirAIeBroker, MirAIeHub
from miraie_ac.constants import statusUrl

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .logger import LOGGER
from .timers import MirAIeTimers, async_fetch_status, hook_status, timers_key

# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.TIME,
    Platform.BUTTON,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up mirAIe from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    async with MirAIeHub() as hub:
        broker = MirAIeBroker()
        await hub.init(entry.data["username"], entry.data["password"], broker)
        hass.data[DOMAIN][entry.entry_id] = hub

    await _async_setup_timers(hass, entry, hub)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop(timers_key(entry.entry_id), None)

    return unload_ok


async def _async_setup_timers(hass: HomeAssistant, entry: ConfigEntry, hub: MirAIeHub) -> None:
    """Tracks each AC's on/off timers. See timers.py."""
    session = async_get_clientsession(hass)
    all_timers: dict[str, MirAIeTimers] = {}
    for device in hub.home.devices:
        timers = MirAIeTimers(device)
        hook_status(timers)
        try:
            await async_fetch_status(session, statusUrl, hub.user.access_token, timers)
        except Exception as error:  # pylint: disable=broad-except
            # Not fatal: the AC's next status message brings the timers.
            LOGGER.debug(f"Could not read the timers of {device.friendly_name}: {error}")
        all_timers[device.id] = timers
    hass.data[DOMAIN][timers_key(entry.entry_id)] = all_timers
