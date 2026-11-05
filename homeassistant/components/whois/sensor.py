"""Get WHOIS information for a given host."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import override

from whoisdomain import Domain

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import CONF_DOMAIN, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_EXPIRES,
    ATTR_NAME_SERVERS,
    ATTR_REGISTRAR,
    ATTR_UPDATED,
    DOMAIN,
    DOMAIN_STATUSES,
    HEALTH_STATES,
    STATUS_TYPES,
)
from .coordinator import WhoisConfigEntry, WhoisCoordinator
from .health import days_until_expiration, get_domain_health, get_domain_status


@dataclass(frozen=True, kw_only=True)
class WhoisSensorEntityDescription(SensorEntityDescription):
    """Describes a Whois sensor entity."""

    value_fn: Callable[[Domain], datetime | int | str | None]


def _ensure_timezone(timestamp: datetime | None) -> datetime | None:
    """Ensure the timestamp has timezone information."""
    if timestamp is None:
        return None

    # If timezone info isn't provided by WHOIS, assume UTC.
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)

    return timestamp


def _get_status_type(status: str | None) -> str | None:
    """Get the status type from the status string.

    Return the status type in snake_case for translations.

    E.g: "clientDeleteProhibited https://icann.org/epp#clientDeleteProhibited"
    -> "client_delete_prohibited".
    """
    if status is None:
        return None

    # If the status is not in STATUS_TYPES, return the status as is.
    for icann_status, hass_status in STATUS_TYPES.items():
        if icann_status in status:
            return hass_status

    # If the status is not in STATUS_TYPES, return None.
    return None


SENSORS: tuple[WhoisSensorEntityDescription, ...] = (
    WhoisSensorEntityDescription(
        key="admin",
        translation_key="admin",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda domain: getattr(domain, "admin", None),
    ),
    WhoisSensorEntityDescription(
        key="creation_date",
        translation_key="creation_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda domain: _ensure_timezone(domain.creation_date),
    ),
    WhoisSensorEntityDescription(
        key="days_until_expiration",
        translation_key="days_until_expiration",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=days_until_expiration,
    ),
    WhoisSensorEntityDescription(
        key="domain_health",
        translation_key="domain_health",
        device_class=SensorDeviceClass.ENUM,
        options=HEALTH_STATES,
        value_fn=get_domain_health,
    ),
    WhoisSensorEntityDescription(
        key="domain_status",
        translation_key="domain_status",
        device_class=SensorDeviceClass.ENUM,
        options=DOMAIN_STATUSES,
        value_fn=get_domain_status,
    ),
    WhoisSensorEntityDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUS_TYPES.values()),
        entity_registry_enabled_default=False,
        value_fn=lambda domain: _get_status_type(domain.status),
    ),
    WhoisSensorEntityDescription(
        key="expiration_date",
        translation_key="expiration_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda domain: _ensure_timezone(domain.expiration_date),
    ),
    WhoisSensorEntityDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda domain: _ensure_timezone(domain.updated_date),
    ),
    WhoisSensorEntityDescription(
        key="owner",
        translation_key="owner",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda domain: getattr(domain, "owner", None),
    ),
    WhoisSensorEntityDescription(
        key="registrant",
        translation_key="registrant",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda domain: getattr(domain, "registrant", None),
    ),
    WhoisSensorEntityDescription(
        key="registrar",
        translation_key="registrar",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda domain: domain.registrar or None,
    ),
    WhoisSensorEntityDescription(
        key="reseller",
        translation_key="reseller",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda domain: getattr(domain, "reseller", None),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhoisConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the platform from config_entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            WhoisSensorEntity(
                coordinator=coordinator,
                description=description,
                domain=entry.data[CONF_DOMAIN],
            )
            for description in SENSORS
        ],
    )


class WhoisSensorEntity(CoordinatorEntity[WhoisCoordinator], SensorEntity):
    """Implementation of a WHOIS sensor."""

    entity_description: WhoisSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WhoisCoordinator,
        description: WhoisSensorEntityDescription,
        domain: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{domain}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, domain)},
            name=domain,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._domain = domain

    @property
    @override
    def native_value(self) -> datetime | int | str | None:
        """Return the state of the sensor."""
        if (domain := self.coordinator.data) is None:
            return None

        if self.entity_description.key == "domain_health":
            return get_domain_health(domain, self.coordinator.detected_changes)

        return self.entity_description.value_fn(domain)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the state attributes of the monitored installation."""
        # Only add attributes to the original days-until-expiration sensor.
        if self.entity_description.key != "days_until_expiration":
            return None

        if self.coordinator.data is None:
            return None

        attrs: dict[str, str] = {}

        if expiration_date := self.coordinator.data.expiration_date:
            attrs[ATTR_EXPIRES] = expiration_date.isoformat()

        if name_servers := self.coordinator.data.name_servers:
            attrs[ATTR_NAME_SERVERS] = " ".join(name_servers)

        if updated_date := self.coordinator.data.updated_date:
            attrs[ATTR_UPDATED] = updated_date.isoformat()

        if registrar := self.coordinator.data.registrar:
            attrs[ATTR_REGISTRAR] = registrar

        if not attrs:
            return None

        return attrs
