"""Background lifecycle for the durable outbound Webmention queue."""

import copy
import threading
from datetime import datetime, timedelta, timezone

from .delivery import _delivery_result, deliver_webmention, discover_endpoint
from .outbox import OutboundQueue
from .shared import STATUS_ENTRY_LIMIT, STATUSES, _absolute_url, _status_entry, _status_error


def _clock_time(clock):
    value = clock()
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _time_text(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class OutboundWorker:
    """Asynchronous worker for one private outbound queue.

    The worker has its own run guard and never holds the queue lock while doing
    network work. New events may therefore be enqueued while an endpoint is
    slow. An interrupted delivery leaves the same logical event pending or
    retrying so restart recovery can safely send the same source/target pair.
    """

    def __init__(
        self,
        queue,
        *,
        discoverer=discover_endpoint,
        deliverer=deliver_webmention,
        clock=lambda: datetime.now(timezone.utc),
        after_delivery=None,
    ):
        if not isinstance(queue, OutboundQueue):
            raise ValueError("Outbound worker requires a Webmention outbox.")
        self.queue = queue
        self.discoverer = discoverer
        self.deliverer = deliverer
        self.clock = clock
        self.after_delivery = after_delivery
        self.run_lock = threading.Lock()
        self.thread = None
        self.last_error = None
        self.last_results = []

    def _due(self, record, now):
        if record["status"] == "pending":
            return True
        if record["status"] != "retrying":
            return False
        if not record["next_attempt_at"]:
            return True
        try:
            due = datetime.fromisoformat(record["next_attempt_at"].replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            return due.astimezone(timezone.utc) <= now
        except ValueError:
            return True

    def _save_result(self, record, endpoint, result, now):
        status = result["status"]
        next_attempt = None
        if status == "retrying":
            next_attempt = _time_text(now + timedelta(seconds=result["retry_after"]))
        return self.queue.update(
            record["key"],
            status,
            endpoint=endpoint,
            error=result["error"],
            next_attempt_at=next_attempt,
        )

    def _process(self, record, now):
        attempt = record["attempts"] + 1
        try:
            discovery = self.discoverer(record)
        except ValueError as error:
            result = _delivery_result(None, attempt=attempt, error=str(error))
            return self._save_result(record, record["endpoint"], result, now)
        if discovery is None:
            return self.queue.update(
                record["key"],
                "no_endpoint",
                error="No Webmention endpoint advertised.",
                next_attempt_at=None,
            )
        endpoint = _absolute_url(discovery["endpoint"], keep_fragment=False)
        try:
            result = self.deliverer(record, discovery, attempt=attempt)
        except ValueError as error:
            result = _delivery_result(None, attempt=attempt, error=str(error))
        if self.after_delivery is not None:
            self.after_delivery(record, discovery, result)
        return self._save_result(record, endpoint, result, now)

    def run_due(self):
        if not self.run_lock.acquire(blocking=False):
            return []
        try:
            if self.queue.paused():
                return []
            now = _clock_time(self.clock)
            records = [row for row in self.queue.entries() if self._due(row, now)]
            results = [self._process(record, now) for record in records]
            self.last_results = copy.deepcopy(results)
            return results
        finally:
            self.run_lock.release()

    def start(self):
        """Start one daemon pass and return immediately; false means already running."""
        if self.thread is not None and self.thread.is_alive():
            return False
        self.last_error = None

        def run():
            try:
                self.run_due()
            except BaseException as error:
                self.last_error = error

        self.thread = threading.Thread(target=run, name="Blynger Webmentions", daemon=True)
        self.thread.start()
        return True

    def join(self, timeout=None):
        if self.thread is not None:
            self.thread.join(timeout)
        return self.thread is None or not self.thread.is_alive()


class OutboundService:
    """Run outbound delivery independently of authoring and publication.

    One daemon thread performs an immediate startup pass, wakes after newly
    published work is enqueued, and periodically notices retries that became
    due while Blynger remained open. Queue records remain the durable source of
    truth; a service-level failure never removes work and is retried on a later
    wake or application restart.
    """

    def __init__(
        self,
        queue,
        *,
        discoverer=discover_endpoint,
        deliverer=deliver_webmention,
        clock=lambda: datetime.now(timezone.utc),
        check_interval=60,
    ):
        if not isinstance(queue, OutboundQueue):
            raise ValueError("Outbound service requires a Webmention outbox.")
        if not isinstance(check_interval, (int, float)) or check_interval <= 0:
            raise ValueError("Outbound service check interval must be positive.")
        self.queue = queue
        self.worker = OutboundWorker(
            queue,
            discoverer=discoverer,
            deliverer=deliverer,
            clock=clock,
        )
        self.check_interval = check_interval
        self.guard = threading.RLock()
        self.signal = threading.Event()
        self.thread = None
        self.stopping = False
        self.last_error = None
        self.last_run_at = None

    def _run(self):
        while True:
            with self.guard:
                if self.stopping:
                    return
            self.signal.clear()
            try:
                self.worker.run_due()
                error = None
            except BaseException as exc:
                error = str(exc) or exc.__class__.__name__
            with self.guard:
                self.last_error = error
                self.last_run_at = _time_text(datetime.now(timezone.utc))
                if self.stopping:
                    return
            self.signal.wait(self.check_interval)

    def start(self):
        """Start the service and return immediately; false means already running."""
        with self.guard:
            if self.thread is not None and self.thread.is_alive():
                return False
            self.stopping = False
            self.thread = threading.Thread(
                target=self._run,
                name="Blynger Webmention service",
                daemon=True,
            )
            self.thread.start()
            return True

    def wake(self):
        """Request a prompt pass, starting the service if necessary."""
        self.start()
        self.signal.set()

    def pause(self, value=True):
        """Durably pause or resume new delivery attempts without changing work."""
        paused = self.queue.set_paused(value)
        if paused:
            self.signal.set()
        else:
            self.wake()
        return {"paused": paused}

    def stop(self, timeout=2):
        with self.guard:
            self.stopping = True
            thread = self.thread
        self.signal.set()
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def status(self):
        with self.guard:
            running = self.thread is not None and self.thread.is_alive()
            status = {
                "running": running,
                "paused": self.queue.paused(),
                "last_error": _status_error(self.last_error),
                "last_run_at": self.last_run_at,
                "recovery_notice": _status_error(self.queue.recovery_notice),
                "read_only": self.queue.read_only,
            }
        try:
            rows = self.queue.entries()
            status["counts"] = {
                state: sum(row["status"] == state for row in rows)
                for state in sorted(STATUSES)
            }
            entries = sorted(
                (_status_entry(row) for row in rows),
                key=lambda row: (row["updated_at"], row["key"]),
                reverse=True,
            )
            status["entry_total"] = len(entries)
            status["entries"] = entries[:STATUS_ENTRY_LIMIT]
            status["truncated"] = len(entries) > STATUS_ENTRY_LIMIT
        except Exception as exc:
            status["counts"] = {}
            status["entries"] = []
            status["entry_total"] = 0
            status["truncated"] = False
            status["last_error"] = status["last_error"] or _status_error(str(exc))
        return status


class UnavailableOutboundService:
    """Non-fatal startup fallback when the private outbox cannot be opened."""

    def __init__(self, error):
        self.error = str(error) or error.__class__.__name__

    def start(self):
        return False

    def wake(self):
        raise ValueError(self.error)

    def stop(self, timeout=2):
        return True

    def status(self):
        return {
            "running": False,
            "paused": True,
            "last_error": _status_error(self.error),
            "last_run_at": None,
            "recovery_notice": _status_error(self.error),
            "read_only": True,
            "counts": {},
            "entries": [],
            "entry_total": 0,
            "truncated": False,
        }

    def pause(self, value=True):
        raise ValueError(self.error)
