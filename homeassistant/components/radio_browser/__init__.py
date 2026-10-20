"""The Radio Browser integration."""

from dataclasses import dataclass

from aiodns.error import DNSError
from radios import RadioBrowser, RadioBrowserError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .favorites import FavoriteRadioManager, Favorites
from .random_station import async_get_random_station
from .websocket_api import async_setup as async_setup_ws_api

__all__ = ["async_get_random_station"]


@dataclass
class RadioBrowserData:
    """Class to hold Radio Browser data."""

    radios: RadioBrowser
    favorites: FavoriteRadioManager


type RadioBrowserConfigEntry = ConfigEntry[RadioBrowserData]


async def async_setup_entry(
    hass: HomeAssistant, entry: RadioBrowserConfigEntry
) -> bool:
    """Set up Radio Browser from a config entry.

    This integration doesn't set up any entities, as it provides a media source
    only.
    """
    session = async_get_clientsession(hass)
    radios = RadioBrowser(session=session, user_agent=f"HomeAssistant/{__version__}")
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    try:
        await radios.stats()
    except (DNSError, RadioBrowserError) as err:
        raise ConfigEntryNotReady("Could not connect to Radio Browser API") from err

    entry.runtime_data = RadioBrowserData(radios=radios, favorites=manager)
    async_setup_ws_api(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
