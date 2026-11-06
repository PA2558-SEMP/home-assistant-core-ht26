"""Tests for the Radio Browser favorites WebSocket API."""

from types import SimpleNamespace
from unittest.mock import patch

from aiodns.error import DNSError
import pytest
from radios import RadioBrowserError

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.typing import WebSocketGenerator


@pytest.fixture
def favorite_stations() -> list[dict[str, str]]:
    """Return two stations for favorites tests."""
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
    favorite_stations: list[dict[str, str]],
) -> None:
    """Test remove favorite through WebSocket API."""
    manager = init_integration.runtime_data.favorites

    for station in favorite_stations:
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

    assert favorites == [favorite_stations[1]]


async def test_list_favorites(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    favorite_stations: list[dict[str, str]],
) -> None:
    """Test list favorites through the WebSocket API."""
    for station in favorite_stations:
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
        "result": {"favorites": favorite_stations},
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


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(DNSError, id="dns-error"),
        pytest.param(RadioBrowserError, id="radio-browser-error"),
    ],
)
async def test_add_favorite_fetch_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    exception: type[Exception],
) -> None:
    """Test that station fetching errors return an error without adding favorites."""
    client = await hass_ws_client(hass)
    error = exception("Unable to fetch station")

    with patch.object(
        init_integration.runtime_data.radios,
        "station",
        side_effect=error,
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
            "success": False,
            "error": {
                "code": websocket_api.ERR_UNKNOWN_ERROR,
                "message": str(error),
            },
        }
        mock_station.assert_awaited_once_with(uuid="test-station")

    favorites = await init_integration.runtime_data.favorites.async_load_favorites()

    assert favorites == []
