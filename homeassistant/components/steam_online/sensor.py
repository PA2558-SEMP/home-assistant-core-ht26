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
    PlayerData,
    SteamConfigEntry,
    SteamLibraryCoordinator,
)
from .entity import SteamEntity

PARALLEL_UPDATES = 1


class SteamSensor(StrEnum):
    """Steam sensors."""

    ACCOUNT = "account"
    LAST_ONLINE = "last_online"
    NOW_PLAYING = "now_playing"
    LEVEL = "level"


@dataclass(kw_only=True, frozen=True)
class SteamSensorEntityDescription(SensorEntityDescription):
    """Steam sensor description."""

    value_fn: Callable[[PlayerData], StateType | datetime]
    entity_picture_fn: Callable[[PlayerData, dict[str, str]], str | None] | None = None
    extra_state_attributes_fn: (
        Callable[[PlayerData, dict[str, str]], Mapping[str, Any]] | None
    ) = None


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SteamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Steam platform."""
    coordinator = entry.runtime_data
    if TYPE_CHECKING:
        assert entry.unique_id
    async_add_entities(
        SteamSensorEntity(coordinator, entry.unique_id, description)
        for description in SENSOR_DESCRIPTIONS
        if entry.unique_id in coordinator.data
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
