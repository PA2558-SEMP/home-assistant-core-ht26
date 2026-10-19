"""Tests for Steam sensor platform."""

from collections.abc import Generator
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import steam.api
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.steam_online.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import (
    MockConfigEntry,
    async_load_json_object_fixture,
    snapshot_platform,
)

from . import ACCOUNT_1, ACCOUNT_2


@pytest.fixture(autouse=True)
def sensor_only() -> Generator[None]:
    """Enable only the sensor platform."""
    with patch(
        "homeassistant.components.steam_online.PLATFORMS",
        [Platform.SENSOR],
    ):
        yield


@pytest.mark.usefixtures("steam_api")
async def test_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test setup of the Steam sensor platform."""

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


@pytest.mark.parametrize(
    ("in_game", "news"),
    [
        (False, {}),
        (True, {"return_value": {"appnews": {"appid": 20900, "newsitems": []}}}),
        (True, {"side_effect": steam.api.HTTPError("403")}),
    ],
    ids=["not_in_game", "no_news", "error"],
)
async def test_news_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
    in_game: bool,
    news: dict[str, Any],
) -> None:
    """Test the news sensor is unknown when there is no news to show."""
    if not in_game:
        players = await async_load_json_object_fixture(
            hass, "GetPlayerSummaries.json", DOMAIN
        )
        del players["response"]["players"]["player"][0]["gameid"]
        steam_api.return_value.GetPlayerSummaries.return_value = players
    steam_api.return_value.GetNewsForApp.configure_mock(**news)

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert (state := hass.states.get("sensor.testaccount1_latest_news"))
    assert state.state == STATE_UNKNOWN


@pytest.mark.usefixtures("steam_api")
async def test_friend_activity_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test friend activity sensors with initial Steam API data."""

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    online_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{ACCOUNT_1}_friends_online"
    )
    playing_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{ACCOUNT_1}_friends_playing"
    )

    assert online_entity_id is not None
    assert playing_entity_id is not None

    assert hass.states.get(online_entity_id).state == "1"
    assert hass.states.get(playing_entity_id).state == "0"


async def test_friend_activity_updates(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    steam_api: MagicMock,
) -> None:
    """Test friend activity sensors when a friend starts playing."""

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    online_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{ACCOUNT_1}_friends_online"
    )
    playing_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{ACCOUNT_1}_friends_playing"
    )

    assert online_entity_id is not None
    assert playing_entity_id is not None

    assert hass.states.get(online_entity_id).state == "1"
    assert hass.states.get(playing_entity_id).state == "0"

    client = steam_api.return_value
    response = deepcopy(client.GetPlayerSummaries.return_value)

    for player in response["response"]["players"]["player"]:
        if player["steamid"] == ACCOUNT_2:
            player["personastate"] = 1
            player["gameid"] = "730"
            player["gameextrainfo"] = "Counter-Strike 2"

    client.GetPlayerSummaries.return_value = response

    await config_entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(online_entity_id).state == "1"
    assert hass.states.get(playing_entity_id).state == "1"


async def test_player_and_library_sensors_update_independently(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
) -> None:
    """Test player and library sensors use their own coordinators independently of each other."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    library_coordinator = config_entry.runtime_data.library_coordinator
    coordinator = config_entry.runtime_data

    assert (player_state := hass.states.get("sensor.testaccount1"))
    assert player_state.state == "online"
    assert (games_owned_state := hass.states.get("sensor.testaccount1_games_owned"))
    assert games_owned_state.state == "1"

    # prepare both api responses at the same time
    player_response = await async_load_json_object_fixture(
        hass, "GetPlayerSummaries.json", DOMAIN
    )
    player_response["response"]["players"]["player"][0]["personastate"] = 2
    steam_api.return_value.GetPlayerSummaries.return_value = player_response

    owned_games_response = await async_load_json_object_fixture(
        hass, "GetOwnedGames.json", DOMAIN
    )
    owned_games_response["response"]["game_count"] = 2
    steam_api.return_value.GetOwnedGames.return_value = owned_games_response

    # refresh the coordinators one after another
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert (player_state := hass.states.get("sensor.testaccount1"))
    assert player_state.state == "busy"
    assert (games_owned_state := hass.states.get("sensor.testaccount1_games_owned"))
    assert games_owned_state.state == "1"

    await library_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert (player_state := hass.states.get("sensor.testaccount1"))
    assert player_state.state == "busy"
    assert (games_owned_state := hass.states.get("sensor.testaccount1_games_owned"))
    assert games_owned_state.state == "2"
