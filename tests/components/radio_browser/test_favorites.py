"""Tests for Radio Browser favorites."""

from typing import Any

import pytest
import voluptuous as vol

from homeassistant.components.radio_browser.const import (
    STORAGE_KEY,
    STORAGE_VERSION,
    STORAGE_VERSION_MINOR,
)
from homeassistant.components.radio_browser.favorites import (
    FavoriteRadioManager,
    Favorites,
)
from homeassistant.core import HomeAssistant


async def test_add_favorite(hass: HomeAssistant) -> None:
    """Test adding a station to favorites."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    station = {
        "uuid": "test-station",
        "name": "Test station",
        "url_resolved": "https://example.com/radio.mp3",
        "favicon": "",
        "codec": "MP3",
    }

    await manager.async_add_favorite(station)

    favorites = await manager.async_load_favorites()

    assert favorites == [station]


async def test_remove_favorite(hass: HomeAssistant) -> None:
    """Test removing a favorite from the favorite list."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    station1 = {
        "uuid": "first-station",
        "name": "First station",
        "url_resolved": "https://example.com/station1.mp3",
        "favicon": "",
        "codec": "MP3",
    }
    station2 = {
        "uuid": "second-station",
        "name": "Second station",
        "url_resolved": "https://example.com/station2.mp3",
        "favicon": "",
        "codec": "MP3",
    }

    await manager.async_add_favorite(station1)
    await manager.async_add_favorite(station2)

    await manager.async_remove_favorite("first-station")

    favorites = await manager.async_load_favorites()

    assert favorites == [station2]


async def test_add_duplicate_favorite(hass: HomeAssistant) -> None:
    """Test that the same UUID cannot be added twice."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    station = {
        "uuid": "test-station",
        "name": "Test station 1",
        "url_resolved": "https://example.com/test-station.mp3",
        "favicon": "",
        "codec": "MP3",
    }
    duplicate = {
        "uuid": "test-station",
        "name": "Test station 2",
        "url_resolved": "https://example.com/test-station.mp3",
        "favicon": "",
        "codec": "MP3",
    }

    await manager.async_add_favorite(station)
    await manager.async_add_favorite(duplicate)

    favorites = await manager.async_load_favorites()

    assert favorites == [station]


async def test_remove_non_exsistent_favorite(hass: HomeAssistant) -> None:
    """Test that removing an nonexistent UUID leaves favorites unchanged."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    station = {
        "uuid": "test-station",
        "name": "Test station",
        "url_resolved": "https://example.com/test-station.mp3",
        "favicon": "",
        "codec": "MP3",
    }

    await manager.async_add_favorite(station)
    await manager.async_remove_favorite("station-not-in-list")

    favorites = await manager.async_load_favorites()

    assert favorites == [station]


async def test_remove_from_empty_favorites_list(hass: HomeAssistant) -> None:
    """Test removing a station from an empty favorites list."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    await manager.async_remove_favorite("station-not-in-list")

    favorites = await manager.async_load_favorites()

    assert favorites == []


@pytest.mark.parametrize(
    "station",
    [
        pytest.param({"uuid": "test-station"}, id="missing-name"),
        pytest.param({"name": "Test station"}, id="missing-uuid"),
    ],
)
async def test_add_invalid_favorite(
    hass: HomeAssistant,
    station: dict[str, str],
) -> None:
    """Test that stations missing required fields are rejected."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    with pytest.raises(vol.Invalid):
        await manager.async_add_favorite(station)

    favorites = await manager.async_load_favorites()

    assert favorites == []


async def test_load_favorites(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
) -> None:
    """Test loading multiple saved favorites."""
    stations = [
        {
            "uuid": "test-station-1",
            "name": "Test station 1",
            "url_resolved": "https://example.com/station1.mp3",
            "favicon": "",
            "codec": "MP3",
        },
        {
            "uuid": "test-station-2",
            "name": "Test station 2",
            "url_resolved": "https://example.com/station2.mp3",
            "favicon": "",
            "codec": "MP3",
        },
    ]

    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "minor_version": STORAGE_VERSION_MINOR,
        "key": STORAGE_KEY,
        "data": {"favorites": stations},
    }

    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    favorites = await manager.async_load_favorites()

    assert favorites == stations
