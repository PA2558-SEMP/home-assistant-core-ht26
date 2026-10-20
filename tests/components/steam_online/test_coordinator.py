"""Tests for the Steam coordinators."""

from unittest.mock import MagicMock

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
        steamid=ACCOUNT_1, include_played_free_games=True, include_appinfo=1
    )
    steam_api.return_value.GetBadges.assert_called_once_with(steamid=ACCOUNT_1)

    library_coordinator = config_entry.runtime_data.library_coordinator
    assert library_coordinator.data.games_owned == 1
    assert library_coordinator.data.total_playtime == 6798
    assert library_coordinator.data.xp == 1234
    assert library_coordinator.data.badges == 3
