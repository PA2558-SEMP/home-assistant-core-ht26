"""Tests for WHOIS change detection and notification behavior."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from whoisdomain.exceptions import WhoisCommandFailedError

from homeassistant.components.whois.const import SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from tests.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

CREATE = (
    "homeassistant.components.whois.coordinator.persistent_notification.async_create"
)
DISMISS = (
    "homeassistant.components.whois.coordinator.persistent_notification.async_dismiss"
)
CHANGES_ID = "whois_changes_home-assistant.io"
EXPIRATION_ID = "whois_expiration_home-assistant.io"
ISSUE_ID = "whois_issue_home-assistant.io"
LOOKUP_ID = "whois_lookup_home-assistant.io"
pytestmark = pytest.mark.freeze_time("2022-01-01 12:00:00", tz_offset=0)


async def _refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Advance one scan interval and let the coordinator update."""
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _created_ids(mock_create: MagicMock) -> list[str]:
    """Return the notification ids passed to async_create."""
    return [call.kwargs["notification_id"] for call in mock_create.call_args_list]


async def test_first_update_sets_baseline_without_notification(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test the first successful lookup creates no notification."""
    mock_config_entry.add_to_hass(hass)

    with patch(CREATE) as mock_create:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    mock_create.assert_not_called()
    assert mock_config_entry.runtime_data.detected_changes == {}


@pytest.mark.usefixtures("init_integration")
async def test_registrar_change_creates_one_notification(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test a changed registrar is detected and notified once."""
    domain = mock_whois.return_value
    old_registrar = domain.registrar
    domain.registrar = "New Registrar Inc."

    with patch(CREATE) as mock_create:
        await _refresh(hass, freezer)

    assert _created_ids(mock_create) == [CHANGES_ID]
    assert mock_create.call_args.kwargs["title"] == "WHOIS Domain Changes"
    assert "registrar" in mock_create.call_args.args[1]
    assert mock_config_entry.runtime_data.detected_changes == {
        "registrar": (old_registrar, "New Registrar Inc.")
    }


@pytest.mark.usefixtures("init_integration")
async def test_unchanged_update_does_not_repeat_notification(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test a second update with identical data sends nothing."""
    mock_whois.return_value.registrar = "New Registrar Inc."
    await _refresh(hass, freezer)

    with patch(CREATE) as mock_create:
        await _refresh(hass, freezer)

    mock_create.assert_not_called()
    assert mock_config_entry.runtime_data.detected_changes == {}


@pytest.mark.usefixtures("init_integration")
async def test_missing_field_is_not_a_change(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test a field that disappears from the response is not reported."""
    mock_whois.return_value.registrar = None

    with patch(CREATE) as mock_create:
        await _refresh(hass, freezer)

    mock_create.assert_not_called()
    assert mock_config_entry.runtime_data.detected_changes == {}


@pytest.mark.usefixtures("init_integration")
async def test_failed_lookup_keeps_baseline(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_whois: MagicMock,
) -> None:
    """Test a failed lookup does not reset the baseline."""
    mock_whois.return_value.registrar = "New Registrar Inc."
    mock_whois.side_effect = WhoisCommandFailedError

    with patch(CREATE) as mock_create:
        await _refresh(hass, freezer)
        mock_create.assert_not_called()

        mock_whois.side_effect = None
        await _refresh(hass, freezer)

    assert _created_ids(mock_create) == [CHANGES_ID]


@pytest.mark.usefixtures("init_integration")
async def test_expiration_notification_dismissed_after_renewal(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_whois: MagicMock,
) -> None:
    """Test renewing the domain dismisses the expiration notification."""
    domain = mock_whois.return_value

    domain.expiration_date = dt_util.utcnow() + timedelta(days=60)
    with patch(CREATE) as mock_create, patch(DISMISS) as mock_dismiss:
        await _refresh(hass, freezer)

    assert EXPIRATION_ID in _created_ids(mock_create)
    mock_dismiss.assert_not_called()

    domain.expiration_date = dt_util.utcnow() + timedelta(days=365)
    with patch(CREATE), patch(DISMISS) as mock_dismiss:
        await _refresh(hass, freezer)

    mock_dismiss.assert_called_once()
    assert mock_dismiss.call_args.args[1] == EXPIRATION_ID


@pytest.mark.usefixtures("init_integration")
async def test_critical_status_notifies_once_and_clears(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_whois: MagicMock,
) -> None:
    """Test a suspended domain is reported once and cleared on recovery."""
    domain = mock_whois.return_value
    domain.status = "redemptionPeriod https://icann.org/epp#redemptionPeriod"

    with patch(CREATE) as mock_create:
        await _refresh(hass, freezer)
        await _refresh(hass, freezer)

    assert _created_ids(mock_create).count(ISSUE_ID) == 1
    assert (state := hass.states.get("sensor.home_assistant_io_domain_health"))
    assert state.state == "critical"

    domain.status = "clientTransferProhibited"
    with patch(CREATE), patch(DISMISS) as mock_dismiss:
        await _refresh(hass, freezer)

    mock_dismiss.assert_called_once()
    assert mock_dismiss.call_args.args[1] == ISSUE_ID
    assert (state := hass.states.get("sensor.home_assistant_io_domain_health"))
    assert state.state == "warning"  # the status change itself is a recent change


@pytest.mark.usefixtures("init_integration")
async def test_change_makes_health_warning_for_one_refresh(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_whois: MagicMock,
) -> None:
    """Test a WHOIS change raises health to warning until the next refresh."""
    mock_whois.return_value.registrar = "New Registrar Inc."

    await _refresh(hass, freezer)
    assert (state := hass.states.get("sensor.home_assistant_io_domain_health"))
    assert state.state == "warning"

    await _refresh(hass, freezer)
    assert (state := hass.states.get("sensor.home_assistant_io_domain_health"))
    assert state.state == "healthy"


@pytest.mark.usefixtures("init_integration")
async def test_repeated_lookup_failures_notify_once_and_clear(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_whois: MagicMock,
) -> None:
    """Test a domain that stops answering is reported once and cleared."""
    mock_whois.side_effect = WhoisCommandFailedError

    with patch(CREATE) as mock_create:
        await _refresh(hass, freezer)
        assert LOOKUP_ID not in _created_ids(mock_create)  # a single failure
        await _refresh(hass, freezer)
        await _refresh(hass, freezer)

    assert _created_ids(mock_create) == [LOOKUP_ID]

    mock_whois.side_effect = None
    with patch(DISMISS) as mock_dismiss:
        await _refresh(hass, freezer)

    mock_dismiss.assert_called_once()
    assert mock_dismiss.call_args.args[1] == LOOKUP_ID


@pytest.mark.usefixtures("init_integration")
async def test_alerts_fire_events(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_whois: MagicMock,
) -> None:
    """Test every alert also fires an event for automations."""
    events = async_capture_events(hass, "whois_alert")

    domain = mock_whois.return_value
    domain.registrar = "New Registrar Inc."
    domain.expiration_date = dt_util.utcnow() + timedelta(days=60)
    await _refresh(hass, freezer)

    assert {event.data["type"] for event in events} == {"changes", "expiration"}
    assert all(event.data["domain"] == "home-assistant.io" for event in events)
    expiration = next(e for e in events if e.data["type"] == "expiration")
    assert expiration.data["level"] == "warning"

    # Unchanged data fires nothing more.
    count = len(events)
    await _refresh(hass, freezer)
    assert len(events) == count


@pytest.mark.usefixtures("init_integration")
async def test_alert_also_sends_html5_popup(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
    mock_whois: MagicMock,
) -> None:
    """Test an alert also pops up in every HTML5 push browser."""
    entity_registry.async_get_or_create(
        "notify", "html5", "laptop", suggested_object_id="laptop"
    )
    calls = async_mock_service(hass, "notify", "send_message")

    mock_whois.return_value.registrar = "New Registrar Inc."
    await _refresh(hass, freezer)

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["notify.laptop"]
    assert calls[0].data["title"] == "WHOIS Domain Changes"
