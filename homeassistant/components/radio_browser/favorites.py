"""Class to manage radio browser favorites list."""

from typing import Any, override

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION, STORAGE_VERSION_MINOR

STATION_SCHEMA = vol.Schema(
    {
        vol.Required("uuid"): str,
        vol.Required("name"): str,
        vol.Optional("url_resolved"): str,
        vol.Optional("favicon"): str,
        vol.Optional("codec"): str,
    },
    extra=vol.PREVENT_EXTRA,
)


class Favorites(Store[dict[str, Any]]):
    """Class to manage favorites."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the favorites."""
        super().__init__(
            hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_VERSION_MINOR
        )

    @override
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Migrate to the new version."""
        if old_major_version == 1:
            return {"favorites": old_data.get("favorites", [])}
        return old_data


class FavoriteRadioManager:
    """Class to manage favorite radios."""

    def __init__(self, store: Store[dict[str, Any]]) -> None:
        """Initialize the favorite radio manager."""
        self._store = store
        self.favorites: list[dict[str, Any]] = []

    def _data_to_save(self) -> dict:
        """Return the data to save."""
        return {"favorites": self.favorites}

    async def async_load(self) -> None:
        """Load the favorites from storage."""
        data = await self._store.async_load()
        self.favorites = data.get("favorites", []) if isinstance(data, dict) else []

    async def async_load_favorites(self) -> list[dict]:
        """Get the list of favorite radios."""
        return list(self.favorites)

    async def async_add_favorite(self, radio: dict) -> None:
        """Add a radio to favorites."""
        validated = STATION_SCHEMA(radio)
        if validated["uuid"] not in [fav["uuid"] for fav in self.favorites]:
            self.favorites.append(validated)
            self._store.async_delay_save(self._data_to_save, 1.0)

    async def async_remove_favorite(self, uuid: str) -> None:
        """Remove a radio from favorites."""
        favorites = await self.async_load_favorites()
        remaining_favorites = [fav for fav in favorites if fav["uuid"] != uuid]
        if len(remaining_favorites) != len(favorites):
            self.favorites = remaining_favorites
            self._store.async_delay_save(self._data_to_save, 1.0)
