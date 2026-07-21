"""Simple double-clap detector.

Claps are short, broadband, high-amplitude transients. We look for two
sharp energy spikes in the mic stream that occur within a short window
(default 600ms) of each other, with a quiet gap between them (so it
doesn't fire on continuous loud speech/music).

This is intentionally simple and dependency-free (just numpy) so it can
run alongside the wake-word model on the same audio callback.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class ClapDetectorConfig:
    sample_rate: int = 16000
    frame_ms: int = 20
    spike_threshold_rms: float = 0.35   # relative to rolling noise floor
    quiet_threshold_rms: float = 0.08
    min_gap_ms: int = 80                # min silence between the two claps
    max_gap_ms: int = 600               # max time between the two claps
    noise_floor_alpha: float = 0.98     # EMA smoothing for ambient noise


class DoubleClapDetector:
    """Feed it raw float32 mono frames; call `push()` per frame."""

    def __init__(self, config: ClapDetectorConfig | None = None):
        self.cfg = config or ClapDetectorConfig()
        self._noise_floor = 0.01
        self._last_clap_ts: float | None = None
        self._armed_for_second_clap = False
        self._recent_rms: deque[float] = deque(maxlen=5)

    def _rms(self, frame: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(frame)) + 1e-12))

    def push(self, frame: np.ndarray) -> bool:
        """Returns True the instant a double-clap is confirmed."""
        rms = self._rms(frame)
        now = time.monotonic()

        is_spike = rms > max(self._noise_floor * (1 + self.cfg.spike_threshold_rms), 0.02)
        is_quiet = rms < self._noise_floor + self.cfg.quiet_threshold_rms

        # keep an adaptive noise floor, but don't let claps pollute it
        if not is_spike:
            self._noise_floor = (
                self.cfg.noise_floor_alpha * self._noise_floor
                + (1 - self.cfg.noise_floor_alpha) * rms
            )

        self._recent_rms.append(rms)

        if is_spike:
            if self._last_clap_ts is None:
                self._last_clap_ts = now
                self._armed_for_second_clap = True
                return False

            gap_ms = (now - self._last_clap_ts) * 1000
            if self._armed_for_second_clap and self.cfg.min_gap_ms <= gap_ms <= self.cfg.max_gap_ms:
                self._last_clap_ts = None
                self._armed_for_second_clap = False
                return True

            # spike came too fast (still first clap's tail) — ignore
            if gap_ms < self.cfg.min_gap_ms:
                return False

            # too slow — treat this as a fresh "first" clap
            self._last_clap_ts = now
            self._armed_for_second_clap = True
            return False

        # timeout the pending first clap if we waited too long
        if self._last_clap_ts is not None:
            gap_ms = (now - self._last_clap_ts) * 1000
            if gap_ms > self.cfg.max_gap_ms:
                self._last_clap_ts = None
                self._armed_for_second_clap = False

        return False
