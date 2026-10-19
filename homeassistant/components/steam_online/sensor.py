"""Sensor for Steam account status."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import MAX_LENGTH_STATE_STATE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STEAM_API_URL,
    STEAM_HEADER_IMAGE_FILE,
    STEAM_ICON_URL,
    STEAM_MAIN_IMAGE_FILE,
    STEAM_STATUSES,
    SUBENTRY_TYPE_FRIEND,
)
from .coordinator import (
    AchievementGame,
    LibraryData,
    NewsItem,
    PlayerData,
    SteamConfigEntry,
    SteamDataUpdateCoordinator,
    SteamLibraryCoordinator,
)
from .entity import SteamEntity, SteamLibEntity

PARALLEL_UPDATES = 1


class SteamSensor(StrEnum):
    """Steam sensors."""

    ACCOUNT = "account"
    LAST_ONLINE = "last_online"
    NOW_PLAYING = "now_playing"
    LEVEL = "level"
    NEWS = "news"

    # Friend Activity
    FRIENDS_ONLINE = "friends_online"
    FRIENDS_PLAYING = "friends_playing"
    GAMES_OWNED = "games_owned"
    TOTAL_PLAYTIME = "total_playtime"
    XP = "xp"
    BADGES = "badges"


@dataclass(kw_only=True, frozen=True)
class SteamSensorEntityDescription(SensorEntityDescription):
    """Steam sensor description."""

    value_fn: Callable[[PlayerData], StateType | datetime]
    entity_picture_fn: Callable[[PlayerData, dict[str, str]], str | None] | None = None
    extra_state_attributes_fn: (
        Callable[[PlayerData, dict[str, str]], Mapping[str, Any]] | None
    ) = None


@dataclass(kw_only=True, frozen=True)
class SteamLibSensorEntityDescription(SensorEntityDescription):
    """Steam sensor description for the library sensors."""

    value_fn: Callable[[LibraryData], StateType]


LIB_SENSOR_DESCRIPTIONS: tuple[SteamLibSensorEntityDescription, ...] = (
    SteamLibSensorEntityDescription(
        key=SteamSensor.GAMES_OWNED,
        translation_key=SteamSensor.GAMES_OWNED,
        value_fn=lambda x: x.games_owned,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SteamLibSensorEntityDescription(
        key=SteamSensor.TOTAL_PLAYTIME,
        translation_key=SteamSensor.TOTAL_PLAYTIME,
        value_fn=lambda x: x.total_playtime,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL,
    ),
    SteamLibSensorEntityDescription(
        key=SteamSensor.XP,
        translation_key=SteamSensor.XP,
        value_fn=lambda x: x.xp,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SteamLibSensorEntityDescription(
        key=SteamSensor.BADGES,
        translation_key=SteamSensor.BADGES,
        value_fn=lambda x: x.badges,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

SENSOR_DESCRIPTIONS: tuple[SteamSensorEntityDescription, ...] = (
    SteamSensorEntityDescription(
        key=SteamSensor.ACCOUNT,
        translation_key=SteamSensor.ACCOUNT,
        value_fn=lambda x: STEAM_STATUSES[x.personastate],
        device_class=SensorDeviceClass.ENUM,
        options=list(STEAM_STATUSES.values()),
        entity_picture_fn=lambda x, _: x.avatarfull,
        name=None,
        # Attributes game, game_id, game_image_header, game_image_main, game_icon,
        # last_online, and level are deprecated and can be removed in 2027.2
        extra_state_attributes_fn=lambda x, icons: {
            "real_name": x.realname,
            "created": (
                dt_util.as_local(dt_util.utc_from_timestamp(x.timecreated))
                if x.timecreated is not None
                else None
            ),
            "game": x.gameextrainfo,
            "game_id": x.gameid,
            "game_image_header": (
                f"{STEAM_API_URL}{x.gameid}/{STEAM_HEADER_IMAGE_FILE}"
                if x.gameid is not None
                else None
            ),
            "game_image_main": (
                f"{STEAM_API_URL}{x.gameid}/{STEAM_MAIN_IMAGE_FILE}"
                if x.gameid is not None
                else None
            ),
            "game_icon": (
                f"{STEAM_ICON_URL}{x.gameid}/{info}.jpg"
                if x.gameid is not None and (info := icons.get(x.gameid)) is not None
                else None
            ),
            "last_online": (
                dt_util.utc_from_timestamp(x.lastlogoff)
                if x.lastlogoff is not None
                else None
            ),
            "level": x.level,
        },
    ),
    SteamSensorEntityDescription(
        key=SteamSensor.LAST_ONLINE,
        translation_key=SteamSensor.LAST_ONLINE,
        value_fn=(
            lambda x: (
                dt_util.utc_from_timestamp(x.lastlogoff)
                if x.lastlogoff is not None
                else None
            )
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SteamSensorEntityDescription(
        key=SteamSensor.NOW_PLAYING,
        translation_key=SteamSensor.NOW_PLAYING,
        value_fn=lambda x: x.gameextrainfo,
        entity_picture_fn=lambda x, icons: (
            f"{STEAM_ICON_URL}{x.gameid}/{game_icon_url}.jpg"
            if x.gameid and (game_icon_url := icons.get(x.gameid))
            else None
        ),
        extra_state_attributes_fn=lambda x, _: {"app_id": x.gameid},
    ),
    SteamSensorEntityDescription(
        key=SteamSensor.LEVEL,
        translation_key=SteamSensor.LEVEL,
        value_fn=lambda x: x.level,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

NEWS_DESCRIPTION = SensorEntityDescription(
    key=SteamSensor.NEWS,
    translation_key=SteamSensor.NEWS,
)


@dataclass(kw_only=True, frozen=True)
class FriendActivitySensorEntityDescription(SensorEntityDescription):
    """Description of a friend activity sensor."""

    value_fn: Callable[[list[PlayerData]], int]


FRIEND_ACTIVITY_DESCRIPTIONS = (
    FriendActivitySensorEntityDescription(
        key=SteamSensor.FRIENDS_ONLINE,
        translation_key=SteamSensor.FRIENDS_ONLINE,
        value_fn=lambda friends: sum(
            friend.personastate != 0 for friend in friends
        ),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FriendActivitySensorEntityDescription(
        key=SteamSensor.FRIENDS_PLAYING,
        translation_key=SteamSensor.FRIENDS_PLAYING,
        value_fn=lambda friends: sum(
            bool(friend.gameid) for friend in friends
        ),
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SteamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Steam platform."""
    coordinator = entry.runtime_data
    if TYPE_CHECKING:
        assert entry.unique_id
    if entry.unique_id in coordinator.data:
        async_add_entities(
            [
                *(
                    SteamSensorEntity(coordinator, entry.unique_id, description)
                    for description in SENSOR_DESCRIPTIONS
                ),
                SteamNewsSensorEntity(
                    coordinator,
                    coordinator.library_coordinator,
                    entry.unique_id,
                    NEWS_DESCRIPTION,
                ),
            ]
        )
    async_add_entities(
        SteamLibSensorEntity(
            entry.runtime_data.library_coordinator, entry.unique_id, description
        )
        for description in LIB_SENSOR_DESCRIPTIONS
    )

    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_FRIEND):
        async_add_entities(
            [
                SteamSensorEntity(coordinator, subentry.unique_id, description)
                for description in SENSOR_DESCRIPTIONS
                if subentry.unique_id in coordinator.data
            ],
            config_subentry_id=subentry.subentry_id,
        )
        if entry.unique_id in coordinator.data:
            async_add_entities(
                SteamFriendActivitySensorEntity(
                    coordinator, entry, description
                )
                for description in FRIEND_ACTIVITY_DESCRIPTIONS
            )

    library_coordinator = coordinator.library_coordinator
    games = library_coordinator.data.achievement_games

    if games is not None:
        active_unique_ids = {
            f"{entry.unique_id}_{game.app_id}_achievements" for game in games
        }
        registry = er.async_get(hass)

        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                entity.domain == "sensor"
                and entity.platform == DOMAIN
                and entity.unique_id.startswith(f"{entry.unique_id}_")
                and entity.unique_id.endswith("_achievements")
                and entity.unique_id not in active_unique_ids
            ):
                registry.async_remove(entity.entity_id)

        achievement_sensors = []

        for game in games:
            sensor = SteamAchievementSensorEntity(
                library_coordinator,
                entry.unique_id,
                game,
            )
            achievement_sensors.append(sensor)

        async_add_entities(achievement_sensors)


class SteamSensorEntity(SteamEntity, SensorEntity):
    """Representation of a Steam sensor entity."""

    entity_description: SteamSensorEntityDescription

    @property
    @override
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data[self._steamid])

    @property
    @override
    def entity_picture(self) -> str | None:
        """Return the entity picture to use in the frontend, if any."""
        return (
            fn(self.coordinator.data[self._steamid], self.coordinator.game_icons)
            if (fn := self.entity_description.entity_picture_fn) is not None
            else super().entity_picture
        )

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the state attributes of the sensor."""
        return (
            fn(self.coordinator.data[self._steamid], self.coordinator.game_icons)
            if (fn := self.entity_description.extra_state_attributes_fn) is not None
            else super().extra_state_attributes
        )

class SteamNewsSensorEntity(SteamEntity, SensorEntity):
    """Latest news for the game the main account is playing."""

    _unrecorded_attributes = frozenset({"preview"})

    def __init__(
        self,
        coordinator: SteamDataUpdateCoordinator,
        library_coordinator: SteamLibraryCoordinator,
        steamid: str,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the news sensor."""
        super().__init__(coordinator, steamid, description)
        self.library_coordinator = library_coordinator

    @override
    async def async_added_to_hass(self) -> None:
        """Also listen to the library coordinator."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.library_coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def _news(self) -> NewsItem | None:
        """Return the news item if it belongs to the game being played."""
        news = self.library_coordinator.data.news
        if news and news.appid == self.coordinator.data[self._steamid].gameid:
            return news
        return None

    @property
    @override
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.library_coordinator.last_update_success

    @property
    @override
    def native_value(self) -> str | None:
        """Return the headline of the latest news."""
        return news.title[:MAX_LENGTH_STATE_STATE] if (news := self._news) else None

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the news link, date and preview."""
        if (news := self._news) is None:
            return None
        return {
            "url": news.url,
            "date": dt_util.utc_from_timestamp(news.date),
            "preview": news.contents,
        }


class SteamAchievementSensorEntity(
    CoordinatorEntity[SteamLibraryCoordinator], SensorEntity
):
    """Representation of a steam achievement sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SteamLibraryCoordinator,
        steamid: str,
        achievement_game: AchievementGame,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)

        self._app_id = achievement_game.app_id
        self._attr_name = f"{achievement_game.name} achievements"
        self._attr_unique_id = f"{steamid}_{self._app_id}_achievements"
        self._attr_entity_picture = (
            f"{STEAM_API_URL}{self._app_id}/{STEAM_MAIN_IMAGE_FILE}"
        )
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, steamid)},
        )

    @property
    @override
    def native_value(self) -> str | None:
        """Return achievement progress."""
        for game in self.coordinator.data.achievement_games or []:
            if game.app_id == self._app_id:
                if game.unlocked_achievements is None:
                    return None

                return f"{game.unlocked_achievements} / {game.total_achievements}"

        return None


class SteamFriendActivitySensorEntity(SteamEntity, SensorEntity):
    """Sensor representing aggregated Steam friend activity."""

    entity_description: FriendActivitySensorEntityDescription

    def __init__(
        self,
        coordinator,
        entry: SteamConfigEntry,
        description: FriendActivitySensorEntityDescription,
    ) -> None:
        """Initialize the friend activity sensor."""
        super().__init__(coordinator, entry.unique_id, description)
        self._entry = entry

    @property
    @override
    def native_value(self) -> int:
        """Calculate activity among configured Steam friends."""
        friend_ids = (
            subentry.unique_id
            for subentry in self._entry.get_subentries_of_type(
                SUBENTRY_TYPE_FRIEND
            )
            if subentry.unique_id
        )

        friends = [
            self.coordinator.data[steamid]
            for steamid in friend_ids
            if steamid in self.coordinator.data
        ]

        return self.entity_description.value_fn(friends)


class SteamLibSensorEntity(SteamLibEntity, SensorEntity):
    """Representation of a Steam library sensor entity."""

    entity_description: SteamLibSensorEntityDescription

    @property
    @override
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
