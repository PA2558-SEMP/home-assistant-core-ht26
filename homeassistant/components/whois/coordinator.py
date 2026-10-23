"""DataUpdateCoordinator for the Whois integration."""

from functools import partial
from typing import override

from whoisdomain import Domain, query as whoisdomain_query
from whoisdomain.exceptions import (
    FailedParsingWhoisOutputError,
    UnknownDateFormatError,
    UnknownTldError,
    WhoisCommandFailedError,
)

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CRITICAL_DAYS,
    DOMAIN,
    EVENT_WHOIS_ALERT,
    LOGGER,
    LOOKUP_FAILURE_THRESHOLD,
    SCAN_INTERVAL,
    WARNING_DAYS,
)
from .health import days_until_expiration, has_critical_status

type WhoisConfigEntry = ConfigEntry[WhoisCoordinator]

# Fields to monitor for changes.
MONITORED_FIELDS = ("expiration_date", "registrar", "status")


class WhoisCoordinator(DataUpdateCoordinator[Domain | None]):
    """Class to manage fetching WHOIS data."""

    config_entry: WhoisConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WhoisConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

        # Last successful values of the monitored fields (copies, not the Domain).
        self._previous: dict[str, object] | None = None

        # Store the most recently detected changes.
        self.detected_changes: dict[str, tuple[object, object]] = {}

        # Remember the last expiration alert level.
        self._last_expiration_alert_level: str | None = None

        # Consecutive failed lookups, and whether the user was already told.
        self._failed_lookups = 0
        self._lookup_alert_sent = False

        # Whether a critical-status alert is currently active.
        self._issue_alert_sent = False

    @override
    async def _async_update_data(self) -> Domain | None:
        """Query WHOIS, detect changes, and send notifications."""
        try:
            current_data = await self.hass.async_add_executor_job(
                partial(
                    whoisdomain_query,
                    self.config_entry.data[CONF_DOMAIN],
                    whoisOnly=True,
                )
            )
        except UnknownTldError as ex:
            raise UpdateFailed("Could not set up whois, TLD is unknown") from ex
        except (
            FailedParsingWhoisOutputError,
            WhoisCommandFailedError,
            UnknownDateFormatError,
        ) as ex:
            self._record_lookup_failure()
            raise UpdateFailed("An error occurred during WHOIS lookup") from ex

        # A missing response must not replace the previous baseline.
        if current_data is None:
            self._record_lookup_failure()
            self.detected_changes = {}
            return None

        self._record_lookup_success()

        current = {
            field: getattr(current_data, field, None) for field in MONITORED_FIELDS
        }
        previous, self._previous = self._previous, current

        if previous is None:
            # The first successful response establishes the baseline.
            self.detected_changes = {}
        else:
            # Missing fields are not treated as confirmed changes.
            changes = {
                field: (previous[field], current[field])
                for field in MONITORED_FIELDS
                if previous[field] is not None
                and current[field] is not None
                and previous[field] != current[field]
            }
            self.detected_changes = changes

            if changes:
                LOGGER.info(
                    "WHOIS changes detected for %s: %s",
                    self.config_entry.data[CONF_DOMAIN],
                    ", ".join(changes),
                )
                self._notify_changes(changes)

        self._check_expiration(current_data)
        self._check_status(current_data)
        return current_data

    def _check_expiration(self, data: Domain) -> None:
        """Create a notification when the domain approaches expiration."""
        days_remaining = days_until_expiration(data)

        # Missing expiration information must not trigger an alert.
        if days_remaining is None:
            return

        domain = self.config_entry.data[CONF_DOMAIN]
        notification_id = f"whois_expiration_{domain}"

        if days_remaining > WARNING_DAYS:
            if self._last_expiration_alert_level is not None:
                persistent_notification.async_dismiss(self.hass, notification_id)
            self._last_expiration_alert_level = None
            return

        if days_remaining <= 0:
            level = "expired"
            message = f"The domain {domain} has expired or reached its expiration date."
        elif days_remaining < CRITICAL_DAYS:
            level = "critical"
            message = (
                f"The domain {domain} expires in {days_remaining} days. "
                "Renew it as soon as possible."
            )
        else:
            level = "warning"
            message = f"The domain {domain} expires in {days_remaining} days."

        # Avoid repeating the same alert level on every refresh.
        if level == self._last_expiration_alert_level:
            return

        self._alert(
            "expiration",
            "WHOIS Domain Expiration",
            message,
            notification_id,
            level=level,
            days_remaining=days_remaining,
        )
        self._last_expiration_alert_level = level

    def _notify_changes(self, changes: dict[str, tuple[object, object]]) -> None:
        """Create a notification when monitored WHOIS information changes."""
        domain = self.config_entry.data[CONF_DOMAIN]
        details = "\n".join(
            f"{field}: {old_value} → {new_value}"
            for field, (old_value, new_value) in changes.items()
        )

        self._alert(
            "changes",
            "WHOIS Domain Changes",
            f"WHOIS information changed for {domain}:\n\n{details}",
            f"whois_changes_{domain}",
            changes={
                field: [str(old_value), str(new_value)]
                for field, (old_value, new_value) in changes.items()
            },
        )

    def _record_lookup_failure(self) -> None:
        """Count a failed lookup and alert if a working domain keeps failing."""
        self._failed_lookups += 1
        if (
            self._previous is None  # never worked, e.g. a mistyped domain
            or self._lookup_alert_sent
            or self._failed_lookups < LOOKUP_FAILURE_THRESHOLD
        ):
            return

        domain = self.config_entry.data[CONF_DOMAIN]
        self._alert(
            "lookup_failing",
            "WHOIS Lookup Failing",
            f"WHOIS lookups for {domain} have failed {self._failed_lookups} "
            "times in a row after working before. The domain may have been "
            "suspended or deleted, or the WHOIS server may be unavailable.",
            f"whois_lookup_{domain}",
            failures=self._failed_lookups,
        )
        self._lookup_alert_sent = True

    def _record_lookup_success(self) -> None:
        """Reset the failure counter and clear a lookup alert."""
        self._failed_lookups = 0
        if self._lookup_alert_sent:
            domain = self.config_entry.data[CONF_DOMAIN]
            persistent_notification.async_dismiss(self.hass, f"whois_lookup_{domain}")
            self._lookup_alert_sent = False

    def _check_status(self, data: Domain) -> None:
        """Notify once when the domain gets a suspended or pending-delete status."""
        domain = self.config_entry.data[CONF_DOMAIN]
        notification_id = f"whois_issue_{domain}"

        if not has_critical_status(data):
            if self._issue_alert_sent:
                persistent_notification.async_dismiss(self.hass, notification_id)
                self._issue_alert_sent = False
            return

        if self._issue_alert_sent:
            return

        status = getattr(data, "status", None)
        self._alert(
            "critical_status",
            "WHOIS Domain Issue",
            f"The domain {domain} has a critical WHOIS status ({status}). "
            "It may be suspended or scheduled for deletion.",
            notification_id,
            status=str(status),
        )
        self._issue_alert_sent = True

    def _alert(
        self,
        kind: str,
        title: str,
        message: str,
        notification_id: str,
        **data: object,
    ) -> None:
        """Show a persistent notification and fire an event for automations."""
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=notification_id
        )
        self.hass.bus.async_fire(
            EVENT_WHOIS_ALERT,
            {
                "domain": self.config_entry.data[CONF_DOMAIN],
                "type": kind,
                "title": title,
                "message": message,
                **data,
            },
        )
        self._push_popup(title, message)

    def _push_popup(self, title: str, message: str) -> None:
        """Also send a browser popup to every HTML5 push device."""
        targets = [
            entry.entity_id
            for entry in er.async_get(self.hass).entities.values()
            if entry.platform == "html5"
            and entry.domain == "notify"
            and not entry.disabled
        ]
        if targets:
            self.hass.async_create_task(self._async_push_popup(targets, title, message))

    async def _async_push_popup(
        self, targets: list[str], title: str, message: str
    ) -> None:
        """Send one popup, without ever breaking the update."""
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": targets, "title": title, "message": message},
                blocking=True,
            )
        except HomeAssistantError:
            LOGGER.debug("Popup through HTML5 push failed", exc_info=True)
