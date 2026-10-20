"""Tests for Steam sensor platform."""

from collections.abc import Generator
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
