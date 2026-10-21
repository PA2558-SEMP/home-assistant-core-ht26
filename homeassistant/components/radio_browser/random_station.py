"""Fetch a random radio station from the radio browser."""

import mimetypes
import random
from typing import NamedTuple

from aiodns.error import DNSError
from radios import FilterBy, Order, RadioBrowserError, Station

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER

CODEC_TO_MIMETYPE: dict[str, str] = {
    "MP3": "audio/mpeg",
    "AAC": "audio/aac",
    "AAC+": "audio/aac",
    "OGG": "application/ogg",
}

_CANDIDATE_POOL_SIZE = 50


class RandomStationResult(NamedTuple):
    """Result of a random station fetch."""

    name: str
    url: str
    mime_type: str
    uuid: str


def _get_mime_type(station: Station) -> str | None:
    """Get the mimetype for a station."""
    mime_type = CODEC_TO_MIMETYPE.get(station.codec)
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(station.url)
    return mime_type


async def async_get_random_station(
    hass: HomeAssistant,
    *,
    tag: str | None = None,
    country_code: str | None = None,
) -> RandomStationResult | None:
    """Fetch a random radio station from the browser."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        LOGGER.warning("Random_radio_station: Radio Browser integration is not set up")
        return None

    entry = entries[0]
    if entry.state is not ConfigEntryState.LOADED:
        LOGGER.warning("Random_radio_station: Radio Browser config entry not loaded")
        return None

    radios = entry.runtime_data.radios

    kwargs: dict = {
        "hide_broken": True,
        "order": Order.RANDOM,
        "limit": _CANDIDATE_POOL_SIZE,
        "reverse": False,
    }
    if tag:
        kwargs["filter_by"] = FilterBy.TAG_EXACT
        kwargs["filter_term"] = tag.lower()
    elif country_code:
        kwargs["filter_by"] = FilterBy.COUNTRY_CODE_EXACT
        kwargs["filter_term"] = country_code.upper()

    try:
        stations: list[Station] = await radios.stations(**kwargs)
    except (DNSError, RadioBrowserError) as err:
        LOGGER.error(
            "Random_radio_station: Error fetching stations from Radio Browser: %s", err
        )
        return None

    playable = [s for s in stations if s.codec != "UNKNOWN" and _get_mime_type(s)]
    if not playable:
        LOGGER.warning(
            "Random_radio_station: No playable stations found for tag '%s' or country code '%s'",
            tag,
            country_code,
        )
        return None

    station = random.choice(playable)
    mime_type = _get_mime_type(station)
    assert mime_type

    try:
        await radios.station_click(uuid=station.uuid)
    except (DNSError, RadioBrowserError) as err:
        LOGGER.error(
            "Random_radio_station: Error sending click to Radio Browser for station '%s': %s",
            station.name,
            err,
        )

    return RandomStationResult(
        name=station.name,
        url=station.url_resolved,
        mime_type=mime_type,
        uuid=station.uuid,
    )
