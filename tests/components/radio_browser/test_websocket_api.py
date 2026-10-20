"""Tests for the Radio Browser favorites WebSocket API."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.typing import WebSocketGenerator


async def test_add_favorite(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test adding a favorite through the WebSocket API."""
    station = {
        "uuid": "test-station",
        "name": "Test station",
        "url_resolved": "https://example.com/radio.mp3",
        "favicon": "",
        "codec": "MP3",
    }

    client = await hass_ws_client(hass)

    with patch.object(
        init_integration.runtime_data.radios,
        "station",
        return_value=SimpleNamespace(**station),
    ) as mock_station:
        await client.send_json(
            {
                "id": 1,
                "type": "radio_browser/favorites/add",
                "uuid": "test-station",
            }
        )
        response = await client.receive_json()

        assert response == {
            "id": 1,
            "type": "result",
            "success": True,
            "result": None,
        }
        mock_station.assert_awaited_once_with(uuid="test-station")

    favorites = await init_integration.runtime_data.favorites.async_load_favorites()

    assert favorites == [station]


async def test_remove_favorite(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test remove favorite through WebSocket API."""
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

    manager = init_integration.runtime_data.favorites

    for station in stations:
        await manager.async_add_favorite(station)

    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "uuid": "test-station-1", "type": "radio_browser/favorites/remove"}
    )

    response = await client.receive_json()

    assert response == {
        "id": 1,
        "type": "result",
        "success": True,
        "result": None,
    }

    favorites = await manager.async_load_favorites()

    assert favorites == [stations[1]]


async def test_list_favorites(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test list favorites through the WebSocket API."""
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

    for station in stations:
        await init_integration.runtime_data.favorites.async_add_favorite(station)

    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": "radio_browser/favorites/list",
        }
    )
    response = await client.receive_json()

    assert response == {
        "id": 1,
        "type": "result",
        "success": True,
        "result": {"favorites": stations},
    }


@pytest.mark.usefixtures("init_integration")
async def test_list_empty_favorites(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test listing favorites when no stations have been added."""
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": "radio_browser/favorites/list",
        }
    )
    response = await client.receive_json()

    assert response == {
        "id": 1,
        "type": "result",
        "success": True,
        "result": {"favorites": []},
    }


async def test_add_favorite_not_found(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test adding a station that Radio Browser cannot find."""
    client = await hass_ws_client(hass)

    with patch.object(
        init_integration.runtime_data.radios,
        "station",
        return_value=None,
    ) as mock_station:
        await client.send_json(
            {
                "id": 1,
                "type": "radio_browser/favorites/add",
                "uuid": "unknown-station",
            }
        )
        response = await client.receive_json()

        assert response == {
            "id": 1,
            "type": "result",
            "success": False,
            "error": {
                "code": websocket_api.ERR_NOT_FOUND,
                "message": "Radio station not found",
            },
        }
        mock_station.assert_awaited_once_with(uuid="unknown-station")

    favorites = await init_integration.runtime_data.favorites.async_load_favorites()

    assert favorites == []
