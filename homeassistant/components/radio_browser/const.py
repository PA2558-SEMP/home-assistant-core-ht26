"""Constants for the Radio Browser integration."""

import logging
from typing import Final

DOMAIN: Final = "radio_browser"

LOGGER = logging.getLogger(__package__)

STORAGE_KEY = f"{DOMAIN}_favorites"

STORAGE_VERSION: Final = 1

STORAGE_VERSION_MINOR: Final = 1
