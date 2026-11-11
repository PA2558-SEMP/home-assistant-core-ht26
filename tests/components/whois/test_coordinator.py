"""Tests for the WHOIS coordinator notification behavior."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.components.whois.coordinator import (
    WhoisConfigEntry,
    WhoisCoordinator,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


def _domain_data(days_remaining: int) -> object:
    """Create mock WHOIS data with a given number of days remaining."""
    expiration_date = dt_util.utcnow().replace(tzinfo=None) + timedelta(
        days=days_remaining
    )
    return type("DomainData", (), {"expiration_date": expiration_date})()


async def test_expiration_warning_notification(
    hass: HomeAssistant,
    mock_config_entry: WhoisConfigEntry,
) -> None:
    """Test notification when a domain has 60 days remaining."""
    coordinator = WhoisCoordinator(hass, mock_config_entry)
    domain_data = _domain_data(60)

    with patch(
        "homeassistant.components.whois.coordinator.persistent_notification.async_create"
    ) as mock_notification:
        coordinator._check_expiration(domain_data)

    mock_notification.assert_called_once()
    assert mock_notification.call_args.kwargs["title"] == "WHOIS Domain Expiration"
    assert "expires in " in mock_notification.call_args.args[1]
    assert "days." in mock_notification.call_args.args[1]


async def test_expiration_critical_notification(
    hass: HomeAssistant,
    mock_config_entry: WhoisConfigEntry,
) -> None:
    """Test notification when a domain has 15 days remaining."""
    coordinator = WhoisCoordinator(hass, mock_config_entry)
    domain_data = _domain_data(15)

    with patch(
        "homeassistant.components.whois.coordinator.persistent_notification.async_create"
    ) as mock_notification:
        coordinator._check_expiration(domain_data)

    mock_notification.assert_called_once()
    assert "Renew it as soon as possible" in mock_notification.call_args.args[1]


async def test_expired_domain_notification(
    hass: HomeAssistant,
    mock_config_entry: WhoisConfigEntry,
) -> None:
    """Test notification when a domain has expired."""
    coordinator = WhoisCoordinator(hass, mock_config_entry)
    domain_data = _domain_data(-1)

    with patch(
        "homeassistant.components.whois.coordinator.persistent_notification.async_create"
    ) as mock_notification:
        coordinator._check_expiration(domain_data)

    mock_notification.assert_called_once()
    assert "has expired" in mock_notification.call_args.args[1]


async def test_missing_expiration_does_not_notify(
    hass: HomeAssistant,
    mock_config_entry: WhoisConfigEntry,
) -> None:
    """Test that a missing expiration date does not trigger an alert."""
    coordinator = WhoisCoordinator(hass, mock_config_entry)
    domain_data = type("DomainData", (), {"expiration_date": None})()

    with patch(
        "homeassistant.components.whois.coordinator.persistent_notification.async_create"
    ) as mock_notification:
        coordinator._check_expiration(domain_data)

    mock_notification.assert_not_called()


async def test_same_expiration_level_does_not_repeat_notification(
    hass: HomeAssistant,
    mock_config_entry: WhoisConfigEntry,
) -> None:
    """Test that the same alert level does not trigger repeated notifications."""
    coordinator = WhoisCoordinator(hass, mock_config_entry)
    domain_data = _domain_data(60)

    with patch(
        "homeassistant.components.whois.coordinator.persistent_notification.async_create"
    ) as mock_notification:
        coordinator._check_expiration(domain_data)
        coordinator._check_expiration(domain_data)

    mock_notification.assert_called_once()
