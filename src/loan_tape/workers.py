"""Track this application's workers through cancellation and completed cleanup."""

from collections.abc import Callable
from threading import Event, Thread


class WorkerGroup:
    """Owned by the Tk thread; workers never mutate the registry."""

    def __init__(self) -> None:
        self._workers: list[tuple[Thread, Event | None, Callable[[], None]]] = []
        self.closing = False

    def start(
        self, target: Callable[[], None], name: str, cancelled: Event | None = None
    ) -> Thread:
        if self.closing:
            raise RuntimeError("The application is closing; no new work can start.")
        self._workers = [item for item in self._workers if item[0].is_alive()]
        worker = Thread(target=target, name=name, daemon=False)
        # Keep callbacks alive until the Tk thread reaps them: they can own Tk
        # variables which must also be released on the Tk thread.
        self._workers.append((worker, cancelled, target))
        worker.start()
        return worker

    def cancel_reads(self) -> None:
        self.closing = True
        for _, event, _ in self._workers:
            if event is not None:
                event.set()

    def active_names(self) -> tuple[str, ...]:
        self._workers = [item for item in self._workers if item[0].is_alive()]
        return tuple(worker.name for worker, _, _ in self._workers)
