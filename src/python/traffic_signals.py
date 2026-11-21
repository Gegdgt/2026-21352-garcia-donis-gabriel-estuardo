"""Fixed-time, conflict-free phase schedule in simulated seconds.

No Lab08 default is selected here: durations must form a consistent cycle.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FixedTimeSignals:
    avenue_green: float
    street_green: float
    yellow: float
    all_red: float
    offset: float = 0.0

    def __post_init__(self):
        for value in (self.avenue_green, self.street_green, self.yellow, self.all_red):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Signal durations must be positive and finite')
        if not math.isfinite(self.offset):
            raise ValueError('Signal offset must be finite')

    @property
    def cycle(self):
        return self.avenue_green + self.street_green + 2*self.yellow + 2*self.all_red

    @property
    def avenue_red(self):
        return self.cycle - self.avenue_green - self.yellow

    @property
    def street_red(self):
        return self.cycle - self.street_green - self.yellow

    def validate_cycle(self, expected):
        if not math.isfinite(expected) or not math.isclose(self.cycle, expected, abs_tol=1e-9, rel_tol=0):
            raise ValueError(f'Phases total {self.cycle:g} s, not {expected:g} s')

    def states(self, time):
        """Avenue/street colors; half-open intervals, deterministic during seeks."""
        if not math.isfinite(time):
            raise ValueError('Signal time must be finite')
        phase = (time - self.offset) % self.cycle
        intervals = (
            (self.avenue_green, ('green', 'red')),
            (self.yellow, ('yellow', 'red')),
            (self.all_red, ('red', 'red')),
            (self.street_green, ('red', 'green')),
            (self.yellow, ('red', 'yellow')),
            (self.all_red, ('red', 'red')),
        )
        boundary = 0.0
        for duration, colors in intervals:
            boundary += duration
            if phase < boundary:
                return colors
        return ('red', 'red')
