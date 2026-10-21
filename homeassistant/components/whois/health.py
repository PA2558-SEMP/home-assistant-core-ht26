"""Domain health calculation for the Whois integration."""

from collections.abc import Mapping
from datetime import UTC

from whoisdomain import Domain

from homeassistant.util import dt as dt_util

from .const import (
    CRITICAL_DAYS,
    CRITICAL_STATUS_KEYWORDS,
    HEALTH_CRITICAL,
    HEALTH_HEALTHY,
    HEALTH_WARNING,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PENDING_DELETE,
    STATUS_REDEMPTION,
    STATUS_SUSPENDED,
    WARNING_DAYS,
)


def days_until_expiration(domain: Domain) -> int | None:
    """Return the days until the domain expires, or None if unknown."""
    if (expiration_date := domain.expiration_date) is None:
        return None
    if expiration_date.tzinfo is None:
        expiration_date = expiration_date.replace(tzinfo=UTC)
    return (expiration_date - dt_util.utcnow()).days


def has_critical_status(domain: Domain) -> bool:
    """Return True if the domain has a suspended or pending-delete status."""
    values: list[str] = []
    for attribute in ("status", "statuses"):
        raw = getattr(domain, attribute, None)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (list, tuple, set, frozenset)):
            values.extend(item for item in raw if isinstance(item, str))
    text = "".join(values).lower().replace(" ", "")
    return any(keyword in text for keyword in CRITICAL_STATUS_KEYWORDS)


def get_domain_health(
    domain: Domain, changes: Mapping[str, object] | None = None
) -> str | None:
    """Return the health of a domain.

    Critical: fewer than CRITICAL_DAYS left, or a critical registry status.
    Warning: up to WARNING_DAYS left, or WHOIS data changed on the last refresh.
    Healthy: everything else. None when nothing is known.
    """
    days = days_until_expiration(domain)
    if has_critical_status(domain) or (days is not None and days < CRITICAL_DAYS):
        return HEALTH_CRITICAL
    if days is None:
        return HEALTH_WARNING if changes else None
    if days <= WARNING_DAYS or changes:
        return HEALTH_WARNING
    return HEALTH_HEALTHY


def _registry_status_text(domain: Domain) -> list[str]:
    """Return the registry status strings, lowercase, without spaces."""
    values: list[str] = []
    for attr in ("status", "statuses"):
        value = getattr(domain, attr, None)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(item for item in value if isinstance(item, str))
    return [value.lower().replace(" ", "") for value in values]


def get_domain_status(domain: Domain) -> str | None:
    """Return a simple status, or None when nothing is known."""
    text = " ".join(_registry_status_text(domain))
    if "pendingdelete" in text:
        return STATUS_PENDING_DELETE
    if "redemptionperiod" in text:
        return STATUS_REDEMPTION
    if "clienthold" in text or "serverhold" in text:
        return STATUS_SUSPENDED
    days = days_until_expiration(domain)
    if days is not None and days <= 0:
        return STATUS_EXPIRED
    if days is not None or text:
        return STATUS_ACTIVE
    return None
