"""Tests for the Steam coordinators."""

from unittest.mock import MagicMock

import pytest

from homeassistant.core import HomeAssistant

from . import ACCOUNT_1

from tests.common import MockConfigEntry


async def test_library_coordinator_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
) -> None:
    """Test setup and initial data refresh of the library coordinator."""
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    steam_api.return_value.GetOwnedGames.assert_any_call(
        steamid=ACCOUNT_1, include_played_free_games=True
    )
    steam_api.return_value.GetBadges.assert_called_once_with(steamid=ACCOUNT_1)

    library_coordinator = config_entry.runtime_data.library_coordinator
    assert library_coordinator.data.games_owned == 1
    assert library_coordinator.data.total_playtime == 6798
    assert library_coordinator.data.xp == 1234
    assert library_coordinator.data.badges == 3


@pytest.mark.usefixtures("steam_api")
async def test_achievement_counts(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test achievement counts with unlocked and progress-only records."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    library_coordinator = config_entry.runtime_data.library_coordinator
    achievement_games = library_coordinator.data.achievement_games
    assert achievement_games is not None
    assert [
        (game.app_id, game.unlocked_achievements) for game in achievement_games
    ] == [(20900, 2), (1180660, 2)]


async def test_game_without_achievements(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    steam_api: MagicMock,
) -> None:
    """Test for game with no total achievements."""
    steam_api.return_value.GetTopAchievementsForGames.return_value = {
        "response": {
            "games": [
                {"appid": 20900},
                {"appid": 1180660, "total_achievements": 17},
            ]
        }
    }
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    games = config_entry.runtime_data.library_coordinator.data.achievement_games

    assert games is not None
    assert [game.app_id for game in games] == [1180660]

    steam_api.return_value.GetUserAchievements.assert_called_once_with(
        steamid=ACCOUNT_1,
        appid=1180660,
    )
