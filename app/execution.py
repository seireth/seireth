"""Cancellation and deadlines for actual sandbox operations."""

from dataclasses import dataclass
from threading import Event
from time import monotonic
from typing import Callable


class Cancelled(RuntimeError):
    pass


class Interrupted(RuntimeError):
    pass


@dataclass
class ExecutionContext:
    cancel: Event
    shutdown: Event
    deadline: float
    ownership: Callable[[], bool] = lambda: True

    def check(self) -> None:
        if self.shutdown.is_set() or not self.ownership():
            raise Interrupted("execution interrupted")
        if self.cancel.is_set():
            raise Cancelled("assessment cancelled")
        if monotonic() >= self.deadline:
            raise TimeoutError("assessment deadline exceeded")
