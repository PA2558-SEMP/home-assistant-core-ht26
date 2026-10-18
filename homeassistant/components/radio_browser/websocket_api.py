"""Websocket API for favorites list of Radio Browser."""

from typing import TYPE_CHECKING, Any

from aiodns.error import DNSError
from radios import RadioBrowserError
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

if TYPE_CHECKING:
    from . import RadioBrowserConfigEntry


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up the Radio Browser websocket API."""
    websocket_api.async_register_command(hass, websocket_list_favorites)
    websocket_api.async_register_command(hass, websocket_add_favorite)
    websocket_api.async_register_command(hass, websocket_remove_favorite)


@callback
def _async_get_entry(hass: HomeAssistant) -> RadioBrowserConfigEntry | None:
    """Get the Radio Browser entry."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries or entries[0].state is not ConfigEntryState.LOADED:
        return None
    return entries[0]


@websocket_api.websocket_command(
    {
        vol.Required("type"): "radio_browser/favorites/list",
    }
)
@websocket_api.async_response
async def websocket_list_favorites(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List favorite radio stations."""
    entry = _async_get_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_HOME_ASSISTANT_ERROR,
            "Radio Browser is not set up",
        )
        return
    favorites_list = await entry.runtime_data.favorites.async_load_favorites()
    connection.send_result(
        msg["id"],
        {"favorites": favorites_list},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "radio_browser/favorites/add",
        vol.Required("uuid"): str,
    }
)
@websocket_api.async_response
async def websocket_add_favorite(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Adds a radio station to the favorites list."""
    entry = _async_get_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_HOME_ASSISTANT_ERROR,
            "Radio Browser is not set up",
        )
        return

    try:
        station = await entry.runtime_data.radios.station(uuid=msg["uuid"])
    except (DNSError, RadioBrowserError) as err:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR, str(err))
        return

    if not station:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Radio station not found"
        )
        return

    await entry.runtime_data.favorites.async_add_favorite(
        {
            "uuid": station.uuid,
            "name": station.name,
            "url_resolved": station.url_resolved,
            "favicon": station.favicon,
            "codec": station.codec,
        }
    )
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "radio_browser/favorites/remove",
        vol.Required("uuid"): str,
    }
)
@websocket_api.async_response
async def websocket_remove_favorite(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Removes a radio station from the favorites list."""
    entry = _async_get_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_HOME_ASSISTANT_ERROR,
            "Radio Browser is not set up",
        )
        return

    await entry.runtime_data.favorites.async_remove_favorite(msg["uuid"])
    connection.send_result(msg["id"])
