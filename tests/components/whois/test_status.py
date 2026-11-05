"""Tests for the Whois domain status classification."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from homeassistant.components.whois.health import get_domain_status

pytestmark = pytest.mark.freeze_time("2022-01-01 12:00:00", tz_offset=0)

NOW = datetime(2022, 1, 1, 12, 0, 0, tzinfo=UTC)


def _domain(status: Any = None, days: int | None = 100) -> SimpleNamespace:
    """Build a minimal stand-in for a whoisdomain Domain."""
    expiration = None if days is None else NOW + timedelta(days=days)
    return SimpleNamespace(expiration_date=expiration, status=status)


@pytest.mark.parametrize(
    ("status", "days", "expected"),
    [
        (["clientHold"], 100, "suspended"),
        ("serverHold", 100, "suspended"),
        (["pendingDelete"], 100, "pending_delete"),
        (["redemptionPeriod"], 100, "redemption"),
        # The most serious state wins when several are present.
        (["clientHold", "pendingDelete"], 100, "pending_delete"),
        # Protective locks are not problems.
        (
            ["clientTransferProhibited https://icann.org/epp#clientTransferProhibited"],
            100,
            "active",
        ),
        (None, 100, "active"),
        (None, 1, "active"),
        (None, 0, "expired"),
        (None, -5, "expired"),
        # A known status but no expiration date is still active.
        (["ok"], None, "active"),
        # Nothing known means no claim.
        (None, None, None),
    ],
)
def test_domain_status(status: Any, days: int | None, expected: str | None) -> None:
    """Test that registry data maps to the right simple status."""
    assert get_domain_status(_domain(status, days)) == expected  # type: ignore[arg-type]
