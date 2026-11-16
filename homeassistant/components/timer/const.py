"""Constants for the timer integration."""

from enum import StrEnum


class TimerEntityStateAttribute(StrEnum):
    """State attributes for timer entities."""

    DURATION = "duration"
    EDITABLE = "editable"
    LAST_TRANSITION = "last_transition"
    FINISHES_AT = "finishes_at"
    REMAINING = "remaining"
    RESTORE = "restore"
    # Chain-timer attributes
    CURRENT_PHASE_INDEX = "current_phase_index"
    CURRENT_PHASE_NAME = "current_phase_name"
    CURRENT_CYCLE = "current_cycle"
    TOTAL_CYCLES = "total_cycles"

