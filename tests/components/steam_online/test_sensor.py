"""Tests for Steam sensor platform."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
import steam.api
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.steam_online.const import DOMAIN, LIBRARY_UPDATE_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import (
    MockConfigEntry,
    async_fire_time_changed,
    load_json_object_fixture,
    snapshot_platform,
)

NEWS_ENTITY_ID = "sensor.testaccount1_latest_news"


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


async def _setup(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Set up the integration."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_news_in_game(
    hass: HomeAssistant, config_entry: MockConfigEntry, steam_api: MagicMock
) -> None:
    """Test the news sensor shows the latest news for the game being played."""
    await _setup(hass, config_entry)

    assert (state := hass.states.get(NEWS_ENTITY_ID))
    assert state.state == "The Witcher IV — Cinematic Reveal Trailer"
    assert state.attributes["url"].endswith("/1785774543542053")
    assert state.attributes["date"] == datetime(2024, 12, 13, 1, 16, 50, tzinfo=UTC)
    assert state.attributes["preview"].startswith("We're thrilled")

    kwargs = steam_api.return_value.GetNewsForApp.call_args.kwargs
    assert kwargs["version"] == 2
    assert kwargs["appid"] == "20900"


async def test_news_idle(
    hass: HomeAssistant, config_entry: MockConfigEntry, steam_api: MagicMock
) -> None:
    """Test the news sensor is unknown when no game is played."""
    players = load_json_object_fixture("GetPlayerSummaries.json", DOMAIN)
    del players["response"]["players"]["player"][0]["gameid"]
    steam_api.return_value.GetPlayerSummaries.return_value = players

    await _setup(hass, config_entry)

    assert (state := hass.states.get(NEWS_ENTITY_ID))
    assert state.state == STATE_UNKNOWN
    steam_api.return_value.GetNewsForApp.assert_not_called()


async def test_news_long_headline(
    hass: HomeAssistant, config_entry: MockConfigEntry, steam_api: MagicMock
) -> None:
    """Test a headline over 255 characters is cut."""
    news = load_json_object_fixture("GetNewsForApp.json", DOMAIN)
    news["appnews"]["newsitems"][0]["title"] = "a" * 300
    steam_api.return_value.GetNewsForApp.return_value = news

    await _setup(hass, config_entry)

    assert (state := hass.states.get(NEWS_ENTITY_ID))
    assert state.state == "a" * 255


async def test_news_empty(
    hass: HomeAssistant, config_entry: MockConfigEntry, steam_api: MagicMock
) -> None:
    """Test the news sensor is unknown when the game has no news."""
    steam_api.return_value.GetNewsForApp.return_value = {
        "appnews": {"appid": 20900, "newsitems": [], "count": 0}
    }

    await _setup(hass, config_entry)

    assert (state := hass.states.get(NEWS_ENTITY_ID))
    assert state.state == STATE_UNKNOWN


@pytest.mark.parametrize(
    "error",
    [steam.api.HTTPTimeoutError, steam.api.HTTPError("403")],
)
async def test_news_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
    error: Exception,
) -> None:
    """Test a failing news call does not fail the refresh or start reauth."""
    steam_api.return_value.GetNewsForApp.side_effect = error

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert not hass.config_entries.flow.async_progress()
    assert (state := hass.states.get(NEWS_ENTITY_ID))
    assert state.state == STATE_UNKNOWN


async def test_news_refresh_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test news is fetched once within the refresh interval and again after."""
    news_call = steam_api.return_value.GetNewsForApp
    await _setup(hass, config_entry)
    assert news_call.call_count == 1

    # The player coordinator refreshes, but the game did not change
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert news_call.call_count == 1

    freezer.tick(LIBRARY_UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert news_call.call_count == 2


async def test_no_news_for_friends(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test friends do not get a news sensor."""
    await _setup(hass, config_entry)

    news_entities = [
        entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
        if entry.translation_key == "news"
    ]
    assert [entry.entity_id for entry in news_entities] == [NEWS_ENTITY_ID]
