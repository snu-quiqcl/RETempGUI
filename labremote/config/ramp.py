"""Ramp settings consumed by operations; no device execution."""
from dataclasses import dataclass

@dataclass(frozen=True)
class PowerConfig:
    low_power: float
    max_step_vpp: float
    interval: float

    def __post_init__(self):
        self.validate()

    def validate(self):
        from labremote.config.device_config import validate_ramp_settings
        validate_ramp_settings(self.max_step_vpp, self.interval)
