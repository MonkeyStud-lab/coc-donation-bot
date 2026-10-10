"""Thread-safe bot lifecycle with no GUI, ADB, or file access on import.

Factories are injected so tests can exercise startup/cancellation without a
device. The real bot retains its existing process-level DeviceLease in run().
The controller owns one bot or tool worker until it exits.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from contextvars import copy_context
import traceback
from typing import Callable, Protocol


class BotRunner(Protocol):
    def run(self) -> None: ...
    def request_stop(self) -> None: ...


class RunState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class RunOptions:
    dry_run: bool = False
    debug_save_frames: bool = False
    debug: bool = False
    record: bool = False
    record_every: int = 10


@dataclass(frozen=True)
class LifecycleSnapshot:
    generation: int
    state: RunState
    active: bool
    stop_requested: bool
    closing: bool
    error: str | None
    error_traceback: str | None


def _default_factory(options: RunOptions) -> BotRunner:
    # Keep heavy libraries and live configuration out of module import/tests.
    from coc_bot.bot import DonationBot

    return DonationBot(
        dry_run=options.dry_run,
        debug_save_frames=options.debug_save_frames,
        debug=options.debug,
        record=options.record,
        record_every=max(1, options.record_every),
    )


class BotController:
    """Own the worker until it actually exits, including failed startup.

    start() returns False while busy or closing. stop() never joins the worker
    and never enters an ordinary command queue. Interfaces poll snapshot() on
    their own thread; workers never call widgets or UI dispatch functions.
    """

    def __init__(self, factory: Callable[[RunOptions], BotRunner] = _default_factory):
        self._factory = factory
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._bot: BotRunner | None = None
        self._cancel = threading.Event()
        self._generation = 0
        self._state = RunState.STOPPED
        self._closing = False
        self._error: str | None = None
        self._error_traceback: str | None = None

    @property
    def bot(self) -> BotRunner | None:
        """Temporary desktop compatibility for existing timer/farm reads.

        Browser status must later use structured services, not expose this object.
        """
        with self._lock:
            return self._bot

    def _active_locked(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> LifecycleSnapshot:
        with self._lock:
            return LifecycleSnapshot(
                generation=self._generation,
                state=self._state,
                active=self._active_locked(),
                stop_requested=self._cancel.is_set(),
                closing=self._closing,
                error=self._error,
                error_traceback=self._error_traceback,
            )

    def start(self, options: RunOptions = RunOptions()) -> bool:
        return self._start(self._factory, options)

    def new_controller(self):
        """Use the same injected worker implementation with independent state."""
        return BotController(self._factory)

    def start_job(self, factory: Callable[[RunOptions], BotRunner]) -> bool:
        """Use the same owner and priority Stop for a one-shot device job."""
        return self._start(factory, RunOptions())

    def _start(self, factory: Callable[[RunOptions], BotRunner], options: RunOptions) -> bool:
        with self._lock:
            if self._closing or self._active_locked():
                return False
            self._generation += 1
            self._cancel = threading.Event()
            self._bot = None
            self._error = self._error_traceback = None
            self._state = RunState.STARTING
            self._thread = threading.Thread(
                target=copy_context().run, args=(self._work, options, factory),
                name="donation-bot", daemon=True
            )
            try:
                self._thread.start()
            except Exception as exc:
                self._error = str(exc)
                self._error_traceback = traceback.format_exc()
                self._state = RunState.FAILED
                self._thread = None
                raise
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._active_locked():
                return False
            # Remember Stop even before the factory publishes a bot instance.
            already_requested = self._cancel.is_set()
            self._cancel.set()
            self._state = RunState.STOPPING
            bot = self._bot
        if bot is not None and not already_requested:
            bot.request_stop()
        return True

    def close(self) -> None:
        """Reject new runs and cancel current work; wait separately if needed."""
        with self._lock:
            self._closing = True
        self.stop()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait outside locks; False means ownership must not be released yet."""
        with self._lock:
            worker = self._thread
        if worker is threading.current_thread():
            raise RuntimeError("A bot worker cannot wait for itself")
        if worker is not None:
            worker.join(timeout)
            return not worker.is_alive()
        return True

    def _work(self, options: RunOptions, factory: Callable[[RunOptions], BotRunner]) -> None:
        try:
            bot = factory(options)
            with self._lock:
                self._bot = bot
                canceled = self._cancel.is_set()
                self._state = RunState.STOPPING if canceled else RunState.RUNNING
            if canceled:
                bot.request_stop()
            else:
                # Stop arriving here sets the real bot's stop flag before or
                # during run(). The existing engine owns its cancellation checks.
                bot.run()
        except Exception as exc:
            from coc_bot.adb.client import AdbStopped
            with self._lock:
                if not (self._cancel.is_set() and isinstance(exc, AdbStopped)):
                    self._error = str(exc)
                    self._error_traceback = traceback.format_exc()
        finally:
            with self._lock:
                self._bot = None
                self._state = RunState.FAILED if self._error is not None else RunState.STOPPED
            # active stays True until this thread exits, even after final state.
