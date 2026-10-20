"""Tests for Steam sensor platform."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.steam_online.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import (
    MockConfigEntry,
    async_load_json_object_fixture,
    snapshot_platform,
)

from copy import deepcopy
from unittest.mock import MagicMock

from homeassistant.components.steam_online.const import DOMAIN

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
