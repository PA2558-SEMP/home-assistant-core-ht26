"""Tests for fetching random Radio Browser stations."""

from types import SimpleNamespace
from unittest.mock import patch

from aiodns.error import DNSError
import pytest
from radios import FilterBy, Order, RadioBrowserError

from homeassistant.components.radio_browser.random_station import (
    RandomStationResult,
    async_get_random_station,
)
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


@pytest.fixture
def station() -> SimpleNamespace:
    """Return a playable radio station."""
    return SimpleNamespace(
        uuid="test-station",
        name="Test station",
        codec="MP3",
        url="https://example.com/radio.mp3",
        url_resolved="https://example.com/stream.mp3",
    )


async def test_get_random_station(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    station: SimpleNamespace,
) -> None:
    """Test returning a playable station and recording its click."""
    radios = init_integration.runtime_data

    with (
        patch.object(
            radios,
            "stations",
            return_value=[station],
        ) as mock_stations,
        patch.object(radios, "station_click") as mock_click,
    ):
        result = await async_get_random_station(hass)

        mock_stations.assert_awaited_once_with(
            hide_broken=True,
            order=Order.RANDOM,
            limit=50,
            reverse=False,
        )
        mock_click.assert_awaited_once_with(uuid="test-station")

    assert result == RandomStationResult(
        name="Test station",
        url="https://example.com/stream.mp3",
        mime_type="audio/mpeg",
        uuid="test-station",
    )


@pytest.mark.parametrize(
    ("tag", "country_code", "filter_by", "filter_term"),
    [
        pytest.param(
            "JAZZ",
            None,
            FilterBy.TAG_EXACT,
            "jazz",
            id="tag-lowercase",
        ),
        pytest.param(
            None,
            "se",
            FilterBy.COUNTRY_CODE_EXACT,
            "SE",
            id="country-uppercase",
        ),
        pytest.param(
            "JAZZ",
            "se",
            FilterBy.TAG_EXACT,
            "jazz",
            id="country-filter-skipped-when-tag-provided",
        ),
    ],
)
async def test_get_random_station_filters(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    tag: str | None,
    country_code: str | None,
    filter_by: FilterBy,
    filter_term: str,
    station: SimpleNamespace,
) -> None:
    """Test the filter arguments sent to Radio Browser."""
    radios = init_integration.runtime_data

    with patch.object(
        radios,
        "stations",
        return_value=[station],
    ) as mock_stations:
        result = await async_get_random_station(
            hass,
            tag=tag,
            country_code=country_code,
        )

        mock_stations.assert_awaited_once_with(
            hide_broken=True,
            order=Order.RANDOM,
            limit=50,
            reverse=False,
            filter_by=filter_by,
            filter_term=filter_term,
        )

    assert result is not None
    assert result.uuid == "test-station"


async def test_radio_browser_returns_empty_list(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test that no stations returns None without recording a click."""
    radios = init_integration.runtime_data

    with (
        patch.object(
            radios,
            "stations",
            return_value=[],
        ) as mock_stations,
        patch.object(radios, "station_click") as mock_click,
    ):
        result = await async_get_random_station(hass)

        mock_stations.assert_awaited_once_with(
            hide_broken=True,
            order=Order.RANDOM,
            limit=50,
            reverse=False,
        )
        mock_click.assert_not_called()

    assert result is None


@pytest.mark.parametrize(
    ("codec", "url"),
    [
        pytest.param(
            "UNKNOWN",
            "https://example.com/radio.mp3",
            id="unknown-codec",
        ),
        pytest.param(
            "",
            "https://example.com/stream",
            id="mime-type-undetermined",
        ),
    ],
)
async def test_unplayable_station(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    station: SimpleNamespace,
    codec: str,
    url: str,
) -> None:
    """Test that unplayable stations return None without recording a click."""
    station.codec = codec
    station.url = url
    radios = init_integration.runtime_data

    with (
        patch.object(radios, "stations", return_value=[station]),
        patch.object(radios, "station_click") as mock_click,
    ):
        result = await async_get_random_station(hass)

        mock_click.assert_not_called()

    assert result is None


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(DNSError, id="dns-error"),
        pytest.param(RadioBrowserError, id="radio-browser-error"),
    ],
)
async def test_fetch_stations_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    exception: type[Exception],
) -> None:
    """Test that a station fetching error returns None."""
    radios = init_integration.runtime_data

    with (
        patch.object(
            radios,
            "stations",
            side_effect=exception,
        ),
        patch.object(radios, "station_click") as mock_click,
    ):
        result = await async_get_random_station(hass)

        mock_click.assert_not_called()

    assert result is None


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(DNSError, id="dns-error"),
        pytest.param(RadioBrowserError, id="radio-browser-error"),
    ],
)
async def test_station_click_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    station: SimpleNamespace,
    exception: type[Exception],
) -> None:
    """Test that a click error does not prevent returning the station."""
    radios = init_integration.runtime_data

    with (
        patch.object(radios, "stations", return_value=[station]),
        patch.object(
            radios,
            "station_click",
            side_effect=exception,
        ) as mock_click,
    ):
        result = await async_get_random_station(hass)

        mock_click.assert_awaited_once_with(uuid=station.uuid)

    assert result == RandomStationResult(
        name=station.name,
        url=station.url_resolved,
        mime_type="audio/mpeg",
        uuid=station.uuid,
    )
