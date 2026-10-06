"""Tests for the Android IP Webcam binary sensor."""

from unittest.mock import MagicMock

from homeassistant.components.android_ip_webcam.binary_sensor import (
    IPWebcamBinarySensor,
)
from homeassistant.components.android_ip_webcam.const import MOTION_ACTIVE


def test_motion_sensor_off() -> None:
    """Test that the motion sensor is off when motion_active is 0.0."""
    coordinator = MagicMock()
    coordinator.cam.get_sensor_value.return_value = 0.0
    coordinator.config_entry.entry_id = "test_entry"

    sensor = IPWebcamBinarySensor(coordinator)

    assert sensor.is_on is False
    coordinator.cam.get_sensor_value.assert_called_once_with(MOTION_ACTIVE)


def test_motion_sensor_on() -> None:
    """Test that the motion sensor is on when motion_active is 1.0."""
    coordinator = MagicMock()
    coordinator.cam.get_sensor_value.return_value = 1.0
    coordinator.config_entry.entry_id = "test_entry"

    sensor = IPWebcamBinarySensor(coordinator)

    assert sensor.is_on is True
    coordinator.cam.get_sensor_value.assert_called_once_with(MOTION_ACTIVE)
