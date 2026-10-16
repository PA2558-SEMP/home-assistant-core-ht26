"""Class to manage favorites."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, VERSION


class Favorites(Store):
    """Class to manage favorites."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the favorites."""
        super().__init__(hass, VERSION, STORAGE_KEY)


class FavoriteRadioManager:
    """Class to manage favorite radios."""

    def __init__(self, store: Store) -> None:
        """Initialize the favorite radio manager."""
        self._store = store

    async def async_add_favorite(self, radio: dict) -> None:
        """Add a radio to favorites."""
        favorites = await self.async_load_favorites()
        if radio not in favorites:
            favorites.append(radio)
            await self._store.async_save(favorites)

    async def async_remove_favorite(self, radio: dict) -> None:
        """Remove a radio from favorites."""
        favorites = await self.async_load_favorites()
        if radio in favorites:
            favorites.remove(radio)
            await self._store.async_save(favorites)

    async def async_load_favorites(self) -> list[dict]:
        """Get the list of favorite radios."""
        return await self._store.async_load() or []
