"""Tests for the Whois domain health calculation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.whois.health import (
    days_until_expiration,
    get_domain_health,
)

NOW = datetime(2022, 1, 1, 12, 0, tzinfo=UTC)


def _domain(expiration_date: datetime | None) -> MagicMock:
    domain = MagicMock()
    domain.expiration_date = expiration_date
    return domain


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (365, "healthy"),
        (91, "healthy"),
        (90, "warning"),
        (31, "warning"),
        (30, "warning"),
        (29, "critical"),
        (1, "critical"),
        (0, "critical"),
        (-5, "critical"),
    ],
)
def test_domain_health(
    freezer: FrozenDateTimeFactory, days: int, expected: str
) -> None:
    """Test the health band for the days left until expiration."""
    freezer.move_to(NOW)
    domain = _domain(NOW + timedelta(days=days))
    assert days_until_expiration(domain) == days
    assert get_domain_health(domain) == expected


def test_domain_health_missing_expiration(freezer: FrozenDateTimeFactory) -> None:
    """Test a TLD without an expiration date gives no health state."""
    freezer.move_to(NOW)
    domain = _domain(None)
    assert days_until_expiration(domain) is None
    assert get_domain_health(domain) is None


def test_naive_expiration_is_treated_as_utc(freezer: FrozenDateTimeFactory) -> None:
    """Test a naive expiration date does not raise and is read as UTC."""
    freezer.move_to(NOW)
    domain = _domain((NOW + timedelta(days=45)).replace(tzinfo=None))
    assert days_until_expiration(domain) == 45
    assert get_domain_health(domain) == "warning"


def test_critical_status_overrides_days(freezer: FrozenDateTimeFactory) -> None:
    """Test a pending-delete status is critical even with years left."""
    freezer.move_to(NOW)
    domain = _domain(NOW + timedelta(days=365))
    domain.status = "pendingDelete https://icann.org/epp#pendingDelete"
    assert get_domain_health(domain) == "critical"


def test_critical_status_without_expiration_date(
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a hold status is critical when the TLD gives no expiration date."""
    freezer.move_to(NOW)
    domain = _domain(None)
    domain.status = "serverHold"
    assert get_domain_health(domain) == "critical"


def test_critical_status_in_status_list(freezer: FrozenDateTimeFactory) -> None:
    """Test a list of statuses is checked too."""
    freezer.move_to(NOW)
    domain = _domain(NOW + timedelta(days=365))
    domain.status = None
    domain.statuses = ["ok", "clientHold"]
    assert get_domain_health(domain) == "critical"


def test_normal_status_is_not_critical(freezer: FrozenDateTimeFactory) -> None:
    """Test the usual transfer-lock statuses do not trigger a false alarm."""
    freezer.move_to(NOW)
    domain = _domain(NOW + timedelta(days=365))
    domain.status = (
        "clientTransferProhibited https://icann.org/epp#clientTransferProhibited"
    )
    assert get_domain_health(domain) == "healthy"


def test_recent_change_makes_healthy_domain_warning(
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a change on the last refresh raises healthy to warning."""
    freezer.move_to(NOW)
    domain = _domain(NOW + timedelta(days=365))
    assert get_domain_health(domain, {"registrar": ("a", "b")}) == "warning"
    assert get_domain_health(domain, {}) == "healthy"


def test_change_without_expiration_date_is_warning(
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a change is a warning even when no expiration date is known."""
    freezer.move_to(NOW)
    assert get_domain_health(_domain(None), {"registrar": ("a", "b")}) == "warning"
