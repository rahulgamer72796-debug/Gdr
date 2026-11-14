"""Shared service primitives: live progress meter + cancellation."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


class CancelledTask(Exception):
    """Raised inside download loops when the user cancels."""


@dataclass
class Progress:
    """Thread-safe progress snapshot (safe to update from yt-dlp hooks)."""

    phase: str = "queued"
    name: str = ""
    done: int = 0
    total: int = 0
    _samples: deque = field(default_factory=lambda: deque(maxlen=12))
    _speed: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cancel: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.time)
    note: str = ""

    # ── writes (any thread) ────────────────────────────────────────────────
    def update(self, done: Optional[int] = None, total: Optional[int] = None,
               phase: Optional[str] = None, name: Optional[str] = None,
               note: Optional[str] = None) -> None:
        with self._lock:
            if done is not None:
                if done < self.done:      # chunk resync after retry
                    self._samples.clear()
                self.done = int(done)
                self._samples.append((time.time(), self.done))
                if len(self._samples) >= 2:
                    (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
                    dt = t1 - t0
                    if dt > 0.2:
                        inst = max(0.0, (d1 - d0) / dt)
                        self._speed = inst if not self._speed else 0.6 * self._speed + 0.4 * inst
            if total is not None:
                self.total = int(total)
            if phase:
                self.phase = phase
                if phase in ("done", "failed", "cancelled"):
                    self._speed = 0.0
            if name:
                self.name = name
            if note is not None:
                self.note = note

    def cancel(self) -> None:
        self._cancel.set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise CancelledTask()

    # ── reads (loop) ───────────────────────────────────────────────────────
    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def speed(self) -> float:
        with self._lock:
            return self._speed

    @property
    def percent(self) -> float:
        with self._lock:
            if not self.total:
                return 0.0
            return min(100.0, self.done / self.total * 100)

    def snapshot(self) -> dict:
        with self._lock:
            total, done, speed = self.total, self.done, self._speed
            remaining = max(0, total - done) if total else 0
            return {
                "phase": self.phase,
                "name": self.name,
                "note": self.note,
                "done": done,
                "total": total,
                "speed": speed,
                "percent": (min(100.0, done / total * 100) if total else 0.0),
                "eta": (remaining / speed if speed and remaining else 0),
            }
