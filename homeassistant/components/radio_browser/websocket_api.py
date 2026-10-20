"""The Radio Browser websocket API."""

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .random_station import async_get_random_station


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up the Radio Browser websocket API."""
    websocket_api.async_register_command(hass, websocket_random_station)


@websocket_api.websocket_command({vol.Required("type"): "radio_browser/random_station"})
@websocket_api.async_response
async def websocket_random_station(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return a random radio station."""
    station = await async_get_random_station(hass)

    if station is None:
        connection.send_error(
            msg["id"],
            "random_station_failed",
            "Could not find a radio station",
        )
        return

    connection.send_result(msg["id"], station._asdict())
