"""Background synchronization between PostgreSQL portal records and Feishu."""

from __future__ import annotations

import threading
import time

import portal_store


class SyncController:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.wake = threading.Event()

    def set(self) -> None:
        """Keep the old stop-event interface used by portal_server."""
        self.stop.set()
        self.wake.set()
        portal_store.set_sync_notifier(None)


def sync_pending_once(client=None, app_token: str | None = None, limit: int = 25) -> dict:
    if client is None or app_token is None:
        from portal_data import _client
        client, app_token = _client()
    from portal_data import _path

    result = {"synced": 0, "failed": 0}
    for item in portal_store.pending_records(limit):
        try:
            remote_id = item.get("feishu_record_id")
            if remote_id:
                record = client.request("PUT", _path(app_token, item["kind"]) + "/records/" + remote_id,
                                        body={"fields": dict(item["pending_fields"])})["record"]
            else:
                record = client.request("POST", _path(app_token, item["kind"]) + "/records",
                                        body={"fields": dict(item["fields"])})["record"]
                remote_id = record["record_id"]
            portal_store.mark_synced(item["kind"], item["local_id"], item["version"], remote_id)
            result["synced"] += 1
        except Exception as error:
            portal_store.mark_failed(item["kind"], item["local_id"], item["version"], str(error))
            result["failed"] += 1
    return result


def pull_from_feishu(client=None, app_token: str | None = None) -> dict:
    if client is None or app_token is None:
        from portal_data import _client
        client, app_token = _client()
    from portal_data import _path

    counts = {}
    for kind in sorted(portal_store.KINDS):
        count = 0
        for record in client.pages(_path(app_token, kind) + "/records"):
            portal_store.mirror_record(kind, record)
            count += 1
        counts[kind] = count
    return counts


def run(stop: threading.Event, wake: threading.Event | None = None,
        fallback_interval: float = 60, pull_interval: float = 300) -> None:
    """Sync on demand, with durable retry timing and a safety-net scan."""
    wake = wake or threading.Event()
    client = app_token = None
    next_pull = 0.0
    while not stop.is_set():
        # Clearing before work preserves notifications that arrive while a
        # Feishu request is in flight: wait() will then return immediately.
        wake.clear()
        try:
            if client is None:
                from portal_data import _client
                client, app_token = _client()
            sync_pending_once(client, app_token)
            if time.monotonic() >= next_pull:
                pull_from_feishu(client, app_token)
                next_pull = time.monotonic() + pull_interval
        except Exception as error:
            print(f"飞书后台同步暂时失败，将自动重试：{error}", flush=True)
            client = app_token = None
            next_pull = time.monotonic() + fallback_interval
        if stop.is_set():
            break
        timeout = fallback_interval
        if next_pull:
            timeout = min(timeout, max(0.05, next_pull - time.monotonic()))
        try:
            retry_delay = portal_store.next_attempt_delay()
            if retry_delay is not None:
                timeout = min(timeout, max(0.05, retry_delay))
        except Exception as error:
            print(f"读取飞书同步队列失败，将在兜底周期重试：{error}", flush=True)
        wake.wait(timeout)


def start() -> SyncController:
    controller = SyncController()
    portal_store.set_sync_notifier(controller.wake.set)
    thread = threading.Thread(target=run, args=(controller.stop, controller.wake),
                              name="portal-feishu-sync", daemon=True)
    thread.start()
    return controller
