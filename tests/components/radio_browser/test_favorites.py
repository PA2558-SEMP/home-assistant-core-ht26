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


@pytest.fixture
async def manager(hass: HomeAssistant) -> FavoriteRadioManager:
    """Return a favorites manager with storage loaded."""
    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()
    return manager


@pytest.fixture
def favorite_station() -> dict[str, str]:
    """Return a station for favorites tests."""
    return {
        "uuid": "test-station",
        "name": "Test station",
        "url_resolved": "https://example.com/radio.mp3",
        "favicon": "",
        "codec": "MP3",
    }


@pytest.fixture
def favorite_stations() -> list[dict[str, str]]:
    """Return two different stations."""
    return [
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


async def test_add_favorite(
    manager: FavoriteRadioManager,
    favorite_station: dict[str, str],
) -> None:
    """Test adding a station to favorites."""
    await manager.async_add_favorite(favorite_station)

    favorites = await manager.async_load_favorites()

    assert favorites == [favorite_station]


async def test_remove_favorite(
    manager: FavoriteRadioManager,
    favorite_stations: list[dict[str, str]],
) -> None:
    """Test removing a favorite from the favorite list."""

    for station in favorite_stations:
        await manager.async_add_favorite(station)

    await manager.async_remove_favorite(favorite_stations[0]["uuid"])

    favorites = await manager.async_load_favorites()

    assert favorites == [favorite_stations[1]]


async def test_add_duplicate_favorite(
    manager: FavoriteRadioManager,
    favorite_station: dict[str, str],
) -> None:
    """Test that the same UUID cannot be added twice."""
    duplicate = {
        "uuid": "test-station",
        "name": "Test station 2",
    }

    await manager.async_add_favorite(favorite_station)
    await manager.async_add_favorite(duplicate)

    favorites = await manager.async_load_favorites()

    assert favorites == [favorite_station]


async def test_remove_nonexsistent_favorite(
    manager: FavoriteRadioManager,
    favorite_station: dict[str, str],
) -> None:
    """Test that removing an nonexistent UUID leaves favorites unchanged."""
    await manager.async_add_favorite(favorite_station)
    await manager.async_remove_favorite("station-not-in-list")

    favorites = await manager.async_load_favorites()

    assert favorites == [favorite_station]


async def test_remove_from_empty_favorites_list(
    manager: FavoriteRadioManager,
) -> None:
    """Test removing a station from an empty favorites list."""
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
    manager: FavoriteRadioManager,
    station: dict[str, str],
) -> None:
    """Test that stations missing required fields are rejected."""
    with pytest.raises(vol.Invalid):
        await manager.async_add_favorite(station)

    favorites = await manager.async_load_favorites()

    assert favorites == []


async def test_load_favorites(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    favorite_stations: list[dict[str, str]],
) -> None:
    """Test loading multiple saved favorites."""
    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "minor_version": STORAGE_VERSION_MINOR,
        "key": STORAGE_KEY,
        "data": {"favorites": favorite_stations},
    }

    manager = FavoriteRadioManager(Favorites(hass))
    await manager.async_load()

    favorites = await manager.async_load_favorites()

    assert favorites == favorite_stations
