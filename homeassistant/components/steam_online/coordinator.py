"""Data update coordinator for the Steam integration."""

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, override

import steam.api

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACHIEVEMENT_LIMIT,
    DOMAIN,
    LIBRARY_UPDATE_INTERVAL,
    NEWS_MAX_LENGTH,
    SUBENTRY_TYPE_FRIEND,
)

type SteamConfigEntry = ConfigEntry[SteamDataUpdateCoordinator]

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True, frozen=True)
class PlayerData:
    """Steam player data."""

    steamid: str
    communityvisibilitystate: int
    profilestate: int | None = None
    personaname: str
    commentpermission: int | None = None
    profileurl: str
    avatar: str
    avatarmedium: str
    avatarfull: str
    avatarhash: str
    lastlogoff: int | None = None
    personastate: int
    realname: str | None = None
    primaryclanid: str | None = None
    timecreated: int | None = None
    personastateflags: int
    loccountrycode: str | None = None
    locstatecode: str | None = None
    loccityid: int | None = None
    gameextrainfo: str | None = None
    gameid: str | None = None
    lobbysteamid: str | None = None
    gameserverip: str | None = None
    gameserversteamid: str | None = None
    level: int | None = None


class SteamDataUpdateCoordinator(DataUpdateCoordinator[dict[str, PlayerData]]):
    """Data update coordinator for the Steam integration."""

    config_entry: SteamConfigEntry
    user_interface: steam.api.interface
    player_interface: steam.api.interface
    library_coordinator: SteamLibraryCoordinator

    def __init__(self, hass: HomeAssistant, config_entry: SteamConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.game_icons: dict[str, str] = {}

    @override
    async def _async_setup(self) -> None:
        """Set up the coordinator."""

        steam.api.key.set(self.config_entry.data[CONF_API_KEY])
        self.user_interface = steam.api.interface("ISteamUser")
        self.player_interface = steam.api.interface("IPlayerService")

    def _update(self) -> dict[str, PlayerData]:
        """Fetch data from API endpoint."""
        if TYPE_CHECKING:
            assert self.config_entry.unique_id
        _ids = [self.config_entry.unique_id]
        _ids.extend(
            subentry.unique_id
            for subentry in self.config_entry.get_subentries_of_type(
                SUBENTRY_TYPE_FRIEND
            )
            if subentry.unique_id
        )

        response = self.user_interface.GetPlayerSummaries(steamids=_ids)
        players = {
            player["steamid"]: PlayerData(
                **player,
                level=self.player_interface.GetSteamLevel(steamid=player["steamid"])[
                    "response"
                ].get("player_level"),
            )
            for player in response["response"]["players"]["player"]
            if player["steamid"] in _ids
        }

        for player in players.values():
            if player.gameid and player.gameid not in self.game_icons:
                games = self.player_interface.GetOwnedGames(
                    steamid=player.steamid,
                    include_appinfo=1,
                    include_played_free_games=True,
                )["response"].get("games", [])
                self.game_icons.update(
                    {str(game["appid"]): game["img_icon_url"] for game in games}
                )

        return players

    @override
    async def _async_update_data(self) -> dict[str, PlayerData]:
        """Send request to the executor."""
        try:
            return await self.hass.async_add_executor_job(self._update)

        except steam.api.HTTPTimeoutError as ex:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="timeout_exception",
            ) from ex
        except steam.api.HTTPError as ex:
            _LOGGER.debug("Full exception:", exc_info=True)
            if "401" in str(ex) or "403" in str(ex):
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="auth_exception",
                ) from ex
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="request_exception",
            ) from ex


@dataclass(kw_only=True, frozen=True)
class NewsItem:
    """Latest news items to get from a game."""

    appid: str
    title: str
    url: str
    date: int
    contents: str


@dataclass(kw_only=True, frozen=True)
class LibraryGame:
    """Steam specific game data."""

    app_id: int
    name: str
    last_played: int | None


@dataclass(kw_only=True, frozen=True)
class AchievementGame:
    """Steam game achievement data."""

    app_id: int
    total_achievements: int
    unlocked_achievements: int | None


@dataclass(kw_only=True, frozen=True)
class LibraryData:
    """Steam account and library data."""

    games: list[LibraryGame] | None
    achievement_games: list[AchievementGame] | None
    games_owned: int | None
    total_playtime: int | None
    xp: int | None
    badges: int | None
    news: NewsItem | None = None


class SteamLibraryCoordinator(DataUpdateCoordinator[LibraryData]):
    """Slower coordinator for the main account's library and badge data."""

    config_entry: SteamConfigEntry
    player_interface: steam.api.interface
    news_interface: steam.api.interface

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SteamConfigEntry,
        player_coordinator: SteamDataUpdateCoordinator,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_library",
            update_interval=LIBRARY_UPDATE_INTERVAL,
        )
        self.player_coordinator = player_coordinator
        self._gameid: str | None = None

    @override
    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        steam.api.key.set(self.config_entry.data[CONF_API_KEY])
        self.player_interface = steam.api.interface("IPlayerService")
        self.news_interface = steam.api.interface("ISteamNews")
        self.config_entry.async_on_unload(
            self.player_coordinator.async_add_listener(self._handle_player_update)
        )

    def _current_gameid(self) -> str | None:
        """Return the game the main account is playing, if any."""
        player = self.player_coordinator.data.get(self.config_entry.unique_id or "")
        return player.gameid if player else None

    @callback
    def _handle_player_update(self) -> None:
        """Refresh right away when the main account switches game."""
        if self._current_gameid() != self._gameid:
            self.config_entry.async_create_task(self.hass, self.async_request_refresh())

    def _fetch_news(self, gameid: str | None) -> NewsItem | None:
        """Fetch the latest news for a game, keeping the old item on errors."""
        if gameid is None:
            return None
        try:
            items = self.news_interface.GetNewsForApp(
                version=2, appid=gameid, count=1, maxlength=NEWS_MAX_LENGTH
            )["appnews"]["newsitems"]
        except steam.api.HTTPError:
            # News is optional, so never fail the refresh or start reauth for it
            _LOGGER.debug("Could not fetch news for %s", gameid, exc_info=True)
            old = self.data.news if self.data else None
            return old if old and old.appid == gameid else None
        if not items:
            return None
        return NewsItem(
            appid=gameid,
            title=items[0]["title"],
            url=items[0]["url"],
            date=items[0]["date"],
            contents=items[0]["contents"],
        )

    def _update(self, gameid: str | None) -> LibraryData:
        """Fetch data from API endpoint."""
        if TYPE_CHECKING:
            assert self.config_entry.unique_id
        steamid = self.config_entry.unique_id

        owned = self.player_interface.GetOwnedGames(
            steamid=steamid, include_played_free_games=True, include_appinfo=1
        )["response"]
        badges = self.player_interface.GetBadges(steamid=steamid)["response"]

        games = owned.get("games")
        library_games = (
            [
                LibraryGame(
                    app_id=game["appid"],
                    name=game["name"],
                    last_played=game.get("rtime_last_played"),
                )
                for game in games
            ]
            if games is not None
            else None
        )

        achievement_games: list[AchievementGame] | None = None

        if library_games is not None:
            achievement_games = []

            recently_played_games = [
                game for game in library_games if game.last_played is not None
            ]
            recently_played_games.sort(
                key=lambda game: game.last_played or 0, reverse=True
            )
            recently_played_games = recently_played_games[:ACHIEVEMENT_LIMIT]

            if recently_played_games:
                game_ids = [game.app_id for game in recently_played_games]

                achievement_re = self.player_interface.GetTopAchievementsForGames(
                    steamid=steamid,
                    appids=game_ids,
                )["response"]

                achievement_games = []

                for game in achievement_re.get("games", []):
                    user_achievement_re = self.player_interface.GetUserAchievements(
                        steamid=steamid,
                        appid=game["appid"],
                    )["response"]

                    user_achievement = user_achievement_re.get("achievements")

                    if user_achievement is None:
                        achievement_games.append(
                            AchievementGame(
                                app_id=game["appid"],
                                total_achievements=game["total_achievements"],
                                unlocked_achievements=None,
                            )
                        )
                        continue
                    unlocked_count = 0
                    has_unlocked = True

                    for achievement in user_achievement:
                        if "unlocked" not in achievement:
                            has_unlocked = False
                            break

                        if achievement["unlocked"]:
                            unlocked_count += 1

                    if has_unlocked:
                        unlocked_achievements = unlocked_count
                    else:
                        unlocked_achievements = None

                    achievement_games.append(
                        AchievementGame(
                            app_id=game["appid"],
                            total_achievements=game["total_achievements"],
                            unlocked_achievements=unlocked_achievements,
                        )
                    )

        return LibraryData(
            games_owned=owned.get("game_count"),
            games=library_games,
            achievement_games=achievement_games,
            total_playtime=(
                sum(game.get("playtime_forever", 0) for game in games)
                if games is not None
                else None
            ),
            xp=badges.get("player_xp"),
            badges=len(badges["badges"]) if "badges" in badges else None,
            news=self._fetch_news(gameid),
        )

    @override
    async def _async_update_data(self) -> LibraryData:
        """Send request to the executor."""
        self._gameid = self._current_gameid()
        try:
            return await self.hass.async_add_executor_job(self._update, self._gameid)

        except steam.api.HTTPTimeoutError as ex:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="timeout_exception",
            ) from ex
        except steam.api.HTTPError as ex:
            _LOGGER.debug("Full exception:", exc_info=True)
            if "401" in str(ex) or "403" in str(ex):
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="auth_exception",
                ) from ex
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="request_exception",
            ) from ex
