"""Validated transmission settings; independent of electrode mapping files."""
from dataclasses import asdict, dataclass
import math
from labremote.configuration.default_profiles import read_default
_DEFAULTS=read_default("dac_timing")


def milliseconds(value, name, maximum=1000):
    if isinstance(value, bool):
        raise ValueError(f'{name}: enter milliseconds between 0 and {maximum}.')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name}: enter a valid number.') from exc
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f'{name}: enter milliseconds between 0 and {maximum}.')
    return number


@dataclass(frozen=True)
class ManualTiming:
    command_gap_ms: float = _DEFAULTS["command_gap_ms"]
    pre_ldac_ms: float = _DEFAULTS["pre_ldac_ms"]
    cooldown_ms: float = _DEFAULTS["cooldown_ms"]

    def validate(self):
        return ManualTiming(milliseconds(self.command_gap_ms, 'Command gap'),
                            milliseconds(self.pre_ldac_ms, 'LDAC wait'),
                            milliseconds(self.cooldown_ms, 'After Apply wait', 5000))

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        return cls(*(milliseconds(data.get(name, getattr(defaults, name)), name,
                                  5000 if name == 'cooldown_ms' else 1000)
                     for name in defaults.as_dict())).validate()


@dataclass(frozen=True)
class SequenceOptions:
    reuse_spi_config: bool = True
    pre_ldac_ms: float = _DEFAULTS["sequence_pre_ldac_ms"]

    def validate(self):
        if type(self.reuse_spi_config) is not bool:
            raise ValueError('Reuse SPI config must be true or false.')
        return SequenceOptions(self.reuse_spi_config,
                               milliseconds(self.pre_ldac_ms, 'Sequence LDAC wait'))

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        return cls(data.get('reuse_spi_config', True),
                   milliseconds(data.get('pre_ldac_ms', _DEFAULTS['sequence_pre_ldac_ms']), 'Sequence LDAC wait')).validate()
