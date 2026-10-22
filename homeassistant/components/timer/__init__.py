"""Support for Timers."""

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any, Self, override

import voluptuous as vol

from homeassistant.const import (  # noqa: F401
    ATTR_EDITABLE,
    ATTR_ENTITY_ID,
    CONF_ICON,
    CONF_ID,
    CONF_NAME,
    SERVICE_RELOAD,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import collection, config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.helpers.service
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType, VolDictType
from homeassistant.util import dt as dt_util

from .const import (
    EVENT_TIMER_PHASE_FINISHED,
    EVENT_TIMER_PHASE_STARTED,
    TimerEntityStateAttribute,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "timer"
ENTITY_ID_FORMAT = DOMAIN + ".{}"

DEFAULT_DURATION = 0
DEFAULT_RESTORE = False

ATTR_DURATION = "duration"
ATTR_REMAINING = "remaining"
ATTR_FINISHES_AT = "finishes_at"
ATTR_RESTORE = "restore"
ATTR_FINISHED_AT = "finished_at"
ATTR_LAST_TRANSITION = "last_transition"

CONF_DURATION = "duration"
CONF_RESTORE = "restore"
CONF_PHASES = "phases"
CONF_ITERATIONS = "iterations"

DEFAULT_ITERATIONS = 1

PHASE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_DURATION): cv.time_period,
    }
)

STATUS_IDLE = "idle"
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"

EVENT_TIMER_FINISHED = "timer.finished"
EVENT_TIMER_CANCELLED = "timer.cancelled"
EVENT_TIMER_CHANGED = "timer.changed"
EVENT_TIMER_STARTED = "timer.started"
EVENT_TIMER_RESTARTED = "timer.restarted"
EVENT_TIMER_PAUSED = "timer.paused"

SERVICE_START = "start"
SERVICE_PAUSE = "pause"
SERVICE_CANCEL = "cancel"
SERVICE_CHANGE = "change"
SERVICE_FINISH = "finish"
SERVICE_NEXT_PHASE = "next_phase"
SERVICE_SKIP_PHASE = "skip_phase"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

STORAGE_FIELDS: VolDictType = {
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_ICON): cv.icon,
    vol.Optional(CONF_DURATION, default=DEFAULT_DURATION): cv.time_period,
    vol.Optional(CONF_RESTORE, default=DEFAULT_RESTORE): cv.boolean,
    vol.Optional(CONF_PHASES, default=[]): [PHASE_SCHEMA],
    vol.Optional(CONF_ITERATIONS, default=DEFAULT_ITERATIONS): vol.All(
        int, vol.Range(min=0)
    ),
}


def _format_timedelta(delta: timedelta) -> str:
    total_seconds = delta.total_seconds()
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours)}:{int(minutes):02}:{int(seconds):02}"


def _none_to_empty_dict[_T](value: _T | None) -> _T | dict[Any, Any]:
    if value is None:
        return {}
    return value


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: cv.schema_with_slug_keys(
            vol.All(
                _none_to_empty_dict,
                {
                    vol.Optional(CONF_NAME): cv.string,
                    vol.Optional(CONF_ICON): cv.icon,
                    vol.Optional(CONF_DURATION, default=DEFAULT_DURATION): vol.All(
                        cv.time_period, _format_timedelta
                    ),
                    vol.Optional(CONF_RESTORE, default=DEFAULT_RESTORE): cv.boolean,
                    vol.Optional(CONF_PHASES, default=[]): [
                        {
                            vol.Required(CONF_NAME): cv.string,
                            vol.Required(CONF_DURATION): vol.All(
                                cv.time_period, _format_timedelta
                            ),
                        }
                    ],
                    vol.Optional(
                        CONF_ITERATIONS, default=DEFAULT_ITERATIONS
                    ): vol.All(int, vol.Range(min=0)),
                },
            )
        )
    },
    extra=vol.ALLOW_EXTRA,
)

RELOAD_SERVICE_SCHEMA = vol.Schema({})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up an input select."""
    component = EntityComponent[Timer](_LOGGER, DOMAIN, hass)
    id_manager = collection.IDManager()

    yaml_collection = collection.YamlCollection(
        logging.getLogger(f"{__name__}.yaml_collection"), id_manager
    )
    collection.sync_entity_lifecycle(
        hass, DOMAIN, DOMAIN, component, yaml_collection, Timer
    )

    storage_collection = TimerStorageCollection(
        Store(hass, STORAGE_VERSION, STORAGE_KEY),
        id_manager,
    )
    collection.sync_entity_lifecycle(
        hass, DOMAIN, DOMAIN, component, storage_collection, Timer
    )

    await yaml_collection.async_load(
        [{CONF_ID: id_, **cfg} for id_, cfg in config.get(DOMAIN, {}).items()]
    )
    await storage_collection.async_load()

    collection.DictStorageCollectionWebsocket(
        storage_collection, DOMAIN, DOMAIN, STORAGE_FIELDS, STORAGE_FIELDS
    ).async_setup(hass)

    async def reload_service_handler(service_call: ServiceCall) -> None:
        """Reload yaml entities."""
        conf = await component.async_prepare_reload(skip_reset=True)
        await yaml_collection.async_load(
            [{CONF_ID: id_, **cfg} for id_, cfg in conf.get(DOMAIN, {}).items()]
        )

    homeassistant.helpers.service.async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_RELOAD,
        reload_service_handler,
        schema=RELOAD_SERVICE_SCHEMA,
    )
    component.async_register_entity_service(
        SERVICE_START,
        {vol.Optional(ATTR_DURATION, default=DEFAULT_DURATION): cv.time_period},
        "async_start",
    )
    component.async_register_entity_service(SERVICE_PAUSE, None, "async_pause")
    component.async_register_entity_service(SERVICE_CANCEL, None, "async_cancel")
    component.async_register_entity_service(SERVICE_FINISH, None, "async_finish")
    component.async_register_entity_service(
        SERVICE_CHANGE,
        {vol.Optional(ATTR_DURATION, default=DEFAULT_DURATION): cv.time_period},
        "async_change",
    )
    component.async_register_entity_service(
        SERVICE_NEXT_PHASE, None, "async_next_phase"
    )
    component.async_register_entity_service(
        SERVICE_SKIP_PHASE, None, "async_next_phase"
    )

    return True


class TimerStorageCollection(collection.DictStorageCollection):
    """Timer storage based collection."""

    CREATE_UPDATE_SCHEMA = vol.Schema(STORAGE_FIELDS)

    @override
    async def _process_create_data(self, data: dict) -> dict:
        """Validate the config is valid."""
        data = self.CREATE_UPDATE_SCHEMA(data)
        # make duration JSON serializeable
        data[CONF_DURATION] = _format_timedelta(data[CONF_DURATION])
        for phase in data.get(CONF_PHASES, []):
            phase[CONF_DURATION] = _format_timedelta(phase[CONF_DURATION])
        return data

    @callback
    @override
    def _get_suggested_id(self, info: dict) -> str:
        """Suggest an ID based on the config."""
        return info[CONF_NAME]  # type: ignore[no-any-return]

    @override
    async def _update_data(self, item: dict, update_data: dict) -> dict:
        """Return a new updated data object."""
        data = {CONF_ID: item[CONF_ID]} | self.CREATE_UPDATE_SCHEMA(update_data)
        # make duration JSON serializeable
        if CONF_DURATION in update_data:
            data[CONF_DURATION] = _format_timedelta(data[CONF_DURATION])
        for phase in data.get(CONF_PHASES, []):
            phase[CONF_DURATION] = _format_timedelta(phase[CONF_DURATION])
        return data  # type: ignore[no-any-return]


class Timer(collection.CollectionEntity, RestoreEntity):
    """Representation of a timer."""

    editable: bool

    def __init__(self, config: ConfigType) -> None:
        """Initialize a timer."""
        self._config: dict = config
        self._last_transition: str | None = None
        self._state: str = STATUS_IDLE
        self._configured_duration = cv.time_period_str(config[CONF_DURATION])
        self._running_duration: timedelta = self._configured_duration
        self._remaining: timedelta | None = None
        self._end: datetime | None = None
        self._listener: Callable[[], None] | None = None
        self._restore: bool = self._config.get(CONF_RESTORE, DEFAULT_RESTORE)
        # Chain-timer state: phases is empty for a plain timer.
        self._phases: list[dict] = config.get(CONF_PHASES, [])
        self._iterations: int = config.get(CONF_ITERATIONS, DEFAULT_ITERATIONS)
        self._current_phase_idx: int = 0
        self._current_cycle: int = 1

        self._attr_should_poll = False
        self._attr_force_update = True

    @classmethod
    @override
    def from_storage(cls, config: ConfigType) -> Self:
        """Return entity instance initialized from storage."""
        timer = cls(config)
        timer.editable = True
        return timer

    @classmethod
    @override
    def from_yaml(cls, config: ConfigType) -> Self:
        """Return entity instance initialized from yaml."""
        timer = cls(config)
        timer.entity_id = ENTITY_ID_FORMAT.format(config[CONF_ID])
        timer.editable = False
        return timer

    @property
    @override
    def name(self) -> str | None:
        """Return name of the timer."""
        return self._config.get(CONF_NAME)

    @property
    @override
    def icon(self) -> str | None:
        """Return the icon to be used for this entity."""
        return self._config.get(CONF_ICON)

    @property
    @override
    def state(self) -> str:
        """Return the current value of the timer."""
        return self._state

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs: dict[str, Any] = {
            TimerEntityStateAttribute.DURATION: _format_timedelta(
                self._running_duration
            ),
            TimerEntityStateAttribute.EDITABLE: self.editable,
            TimerEntityStateAttribute.LAST_TRANSITION: self._last_transition,
        }
        if self._end is not None:
            attrs[TimerEntityStateAttribute.FINISHES_AT] = self._end.isoformat()
        if self._remaining is not None:
            attrs[TimerEntityStateAttribute.REMAINING] = _format_timedelta(
                self._remaining
            )
        if self._restore:
            attrs[TimerEntityStateAttribute.RESTORE] = self._restore
        if self._phases:
            attrs[TimerEntityStateAttribute.CURRENT_PHASE_INDEX] = (
                self._current_phase_idx
            )
            attrs[TimerEntityStateAttribute.CURRENT_PHASE_NAME] = self._phases[
                self._current_phase_idx
            ][CONF_NAME]
            attrs[TimerEntityStateAttribute.CURRENT_CYCLE] = self._current_cycle
            attrs[TimerEntityStateAttribute.TOTAL_CYCLES] = self._iterations

        return attrs

    @property
    @override
    def unique_id(self) -> str | None:
        """Return unique id for the entity."""
        return self._config[CONF_ID]  # type: ignore[no-any-return]

    @override
    async def async_added_to_hass(self) -> None:
        """Call when entity is about to be added to Home Assistant."""
        # If we don't need to restore a previous state or no previous state exists,
        # start at idle
        if not self._restore or (state := await self.async_get_last_state()) is None:
            self._state = STATUS_IDLE
            return

        # Begin restoring state
        self._state = state.state
        self._last_transition = state.attributes.get(
            TimerEntityStateAttribute.LAST_TRANSITION
        )

        # Nothing more to do if the timer is idle
        if self._state == STATUS_IDLE:
            return

        self._running_duration = cv.time_period(
            state.attributes[TimerEntityStateAttribute.DURATION]
        )
        # If the timer was paused, we restore the remaining time
        if self._state == STATUS_PAUSED:
            self._remaining = cv.time_period(
                state.attributes[TimerEntityStateAttribute.REMAINING]
            )
            return
        # If we get here, the timer must have been active so we need to decide what
        # to do based on end time and the current time
        end = cv.datetime(state.attributes[TimerEntityStateAttribute.FINISHES_AT])
        # If there is time remaining in the timer, restore the remaining time then
        # start the timer
        if (remaining := end - dt_util.utcnow().replace(microsecond=0)) > timedelta(0):
            self._remaining = remaining
            self._state = STATUS_PAUSED
            self.async_start()
        # If the timer ended before now, finish the timer. The event will indicate
        # when the timer was expected to fire.
        else:
            self._end = end
            self.async_finish()

    @callback
    def async_start(self, duration: timedelta | None = None) -> None:
        """Start a timer."""
        if self._listener:
            self._listener()
            self._listener = None

        event = EVENT_TIMER_STARTED
        if self._state in (STATUS_ACTIVE, STATUS_PAUSED):
            event = EVENT_TIMER_RESTARTED

        self._state = STATUS_ACTIVE
        start = dt_util.utcnow().replace(microsecond=0)

        # For chain-timers without an explicit override, use the current phase duration.
        if not duration and self._phases:
            duration = cv.time_period(
                self._phases[self._current_phase_idx][CONF_DURATION]
            )

        # Set remaining and running duration unless resuming or restarting
        if duration:
            self._remaining = self._running_duration = duration
        elif not self._remaining:
            self._remaining = self._running_duration

        self._end = start + self._remaining

        self._listener = async_track_point_in_utc_time(
            self.hass, self._async_finished, self._end
        )

        self._fire_event_and_write_state(event)

        if self._phases:
            self._fire_event_and_write_state(
                EVENT_TIMER_PHASE_STARTED,
                extra_attrs={
                    "phase_index": self._current_phase_idx,
                    "phase_name": self._phases[self._current_phase_idx][CONF_NAME],
                    "cycle": self._current_cycle,
                },
            )

    @callback
    def async_change(self, duration: timedelta) -> None:
        """Change duration of a running timer."""
        if self._listener is None or self._end is None:
            raise HomeAssistantError(
                f"Timer {self.entity_id} is not running,"
                " only active timers can be changed"
            )
        # Check against new remaining time before checking boundaries
        new_remaining = (self._end + duration) - dt_util.utcnow().replace(microsecond=0)
        if self._remaining and new_remaining > self._running_duration:
            raise HomeAssistantError(
                f"Not possible to change timer {self.entity_id} beyond duration"
            )
        if self._remaining and (self._remaining + duration) < timedelta():
            raise HomeAssistantError(
                f"Not possible to change timer"
                f" {self.entity_id} to negative time remaining"
            )

        self._listener()
        self._end += duration
        self._remaining = new_remaining
        self._listener = async_track_point_in_utc_time(
            self.hass, self._async_finished, self._end
        )
        # We don't use _fire_event_and_write_state here because we don't want to
        # update last_transition
        self.async_write_ha_state()
        self.hass.bus.async_fire(EVENT_TIMER_CHANGED, {ATTR_ENTITY_ID: self.entity_id})

    @callback
    def async_pause(self) -> None:
        """Pause a timer."""
        if self._listener is None or self._end is None:
            return

        self._listener()
        self._listener = None
        self._remaining = self._end - dt_util.utcnow().replace(microsecond=0)
        self._state = STATUS_PAUSED
        self._end = None
        self._fire_event_and_write_state(EVENT_TIMER_PAUSED)

    @callback
    def async_cancel(self) -> None:
        """Cancel a timer."""
        if self._state == STATUS_IDLE:
            return

        if self._listener:
            self._listener()
            self._listener = None
        self._state = STATUS_IDLE
        self._end = None
        self._remaining = None
        self._running_duration = self._configured_duration
        # Reset chain position so the next start begins from the first phase.
        self._current_phase_idx = 0
        self._current_cycle = 1
        self._fire_event_and_write_state(EVENT_TIMER_CANCELLED)

    @callback
    def async_finish(self) -> None:
        """Reset and updates the states, fire finished event."""
        if self._state == STATUS_IDLE:
            return

        if self._listener:
            self._listener()
            self._listener = None
        end = self._end
        if end is None:
            end = dt_util.utcnow().replace(microsecond=0)
        self._end = None
        self._remaining = None
        self._running_duration = self._configured_duration
        self._current_phase_idx = 0
        self._current_cycle = 1
        self._state = STATUS_IDLE
        self._fire_event_and_write_state(
            EVENT_TIMER_FINISHED, extra_attrs={ATTR_FINISHED_AT: end.isoformat()}
        )

    @callback
    def async_next_phase(self) -> None:
        """Skip to the next phase of a chain-timer."""
        if self._state == STATUS_IDLE:
            raise HomeAssistantError(
                f"Timer {self.entity_id} is not running, only active or paused timers can skip to the next phase"
            )

        if not self._phases:
            raise HomeAssistantError(
                f"Timer {self.entity_id} does not have phases configured"
            )

        if self._listener:
            self._listener()
            self._listener = None
        end = self._end
        if end is None:
            end = dt_util.utcnow().replace(microsecond=0)
        self._end = None
        self._remaining = None
        self._running_duration = self._configured_duration

        if self._advance_chain():
            return

        self._state = STATUS_IDLE
        self._fire_event_and_write_state(
            EVENT_TIMER_FINISHED, extra_attrs={ATTR_FINISHED_AT: end.isoformat()}
        )

    @callback
    def _async_finished(self, time: datetime) -> None:
        """Reset and updates the states, fire finished event."""
        if self._state != STATUS_ACTIVE or self._end is None:
            return

        self._listener = None
        end = self._end
        self._end = None
        self._remaining = None
        self._running_duration = self._configured_duration

        if self._advance_chain():
            return

        self._state = STATUS_IDLE
        self._fire_event_and_write_state(
            EVENT_TIMER_FINISHED, extra_attrs={ATTR_FINISHED_AT: end.isoformat()}
        )

    @callback
    def _advance_chain(self) -> bool:
        """Advance to the next phase or cycle of a chain-timer.

        Returns True if the chain continues (caller should not go idle),
        False if the chain is complete or this is not a chain-timer.
        """
        if not self._phases:
            return False

        self._fire_event_and_write_state(
            EVENT_TIMER_PHASE_FINISHED,
            extra_attrs={
                "phase_index": self._current_phase_idx,
                "phase_name": self._phases[self._current_phase_idx][CONF_NAME],
                "cycle": self._current_cycle,
            },
        )

        next_idx = self._current_phase_idx + 1
        if next_idx < len(self._phases):
            # More phases remain in the current cycle.
            self._current_phase_idx = next_idx
            self._state = STATUS_IDLE
            self.async_start()
            return True

        # All phases in this cycle are done — check if another cycle should start.
        if self._iterations == 0 or self._current_cycle < self._iterations:
            self._current_cycle += 1
            self._current_phase_idx = 0
            self._state = STATUS_IDLE
            self.async_start()
            return True

        # All cycles complete — reset chain position for the next manual start.
        self._current_phase_idx = 0
        self._current_cycle = 1
        return False

    @override
    async def async_update_config(self, config: ConfigType) -> None:
        """Handle when the config is updated."""
        self._config = config
        self._configured_duration = cv.time_period_str(config[CONF_DURATION])
        if self._state == STATUS_IDLE:
            self._running_duration = self._configured_duration
        self._restore = config.get(CONF_RESTORE, DEFAULT_RESTORE)
        self._phases = config.get(CONF_PHASES, [])
        self._iterations = config.get(CONF_ITERATIONS, DEFAULT_ITERATIONS)
        if self._state == STATUS_IDLE:
            self._current_phase_idx = 0
            self._current_cycle = 1
        self.async_write_ha_state()

    def _fire_event_and_write_state(
        self, event: str, *, extra_attrs: dict[str, Any] | None = None
    ) -> None:
        """Fire the event and write state."""
        self._last_transition = event.partition(".")[2]
        self.async_write_ha_state()
        event_data = {ATTR_ENTITY_ID: self.entity_id}
        if extra_attrs:
            event_data.update(extra_attrs)
        self.hass.bus.async_fire(event, event_data)
