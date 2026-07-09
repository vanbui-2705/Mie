"""Proxy lease pool — async port of ProxyManager.cs (KiotProxy only)."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

from app.services.kiotproxy_client import KiotProxyClient, ProxyEndpointData

_KiotProxyClient_instance = KiotProxyClient()
KIOT_TIMEOUT_S = 15.0
IP_LIFETIME = timedelta(minutes=30)


# ─── Lease objects ─────────────────────────────────────────────────────────────

class ProxyLease:
    """A leased proxy slot — mirrors C# ProxyLease."""

    __slots__ = ("_mgr", "_state", "_endpoint", "_completed")

    def __init__(self, mgr: "ProxyManager", state: dict, endpoint: ProxyEndpointData):
        self._mgr = mgr
        self._state = state
        self._endpoint = endpoint
        self._completed = False

    @property
    def endpoint(self) -> ProxyEndpointData:
        return self._endpoint

    def mark_used(self) -> None:
        if self._completed:
            return
        self._completed = True
        # Success: consume a use slot and possibly trigger GetNew
        asyncio.ensure_future(
            self._mgr._complete(self._state, consumed=True)
        )

    def dispose(self) -> None:
        if self._completed:
            return
        self._completed = True
        # Cancel / failure path: release reservation without consuming
        asyncio.ensure_future(
            self._mgr._complete(self._state, consumed=False)
        )


class DirectLease:
    """No-proxy sentinel."""
    endpoint: Optional[ProxyEndpointData] = None
    display: str = "Direct"

    def mark_used(self) -> None: ...
    def dispose(self) -> None: ...


# ─── Manager ──────────────────────────────────────────────────────────────────

class ProxyManager:
    """
    Manages a pool of KiotProxy API keys with:
    - round-robin leasing (ProxyLease)
    - background monitor to refresh expired/depleted proxies
    - version-tag to avoid stale race conditions
    """

    def __init__(self) -> None:
        self._states: list[dict] = []
        self._lock = asyncio.Lock()
        self._stop_event: Optional[asyncio.Event] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._next_idx: int = 0
        self._versions: dict[str, int] = {}
        self._uses_per_proxy: int = 4
        self._check_interval: int = 5
        self._auth_token: str = ""
        self._new_url: str = ""
        self._cur_url: str = ""

    # -- properties ----------------------------------------------------------

    @property
    def is_started(self) -> bool:
        return self._stop_event is not None

    def _stopped(self) -> bool:
        return (
            self._stop_event is not None
            and self._stop_event.is_set()
        )

    # -- configuration -------------------------------------------------------

    def configure(self, raw_keys_text: str) -> None:
        """Build state dicts from raw newline-separated API keys."""
        lines = [
            k.strip()
            for k in raw_keys_text.replace("\r\n", "\n").split("\n")
            if k.strip()
        ]
        seen: set[str] = set()
        unique: list[str] = []
        for k in lines:
            if k not in seen:
                seen.add(k)
                unique.append(k)

        self._states = [self._mk(i, k) for i, k in enumerate(unique)]
        self._versions.clear()
        self._next_idx = 0

    @staticmethod
    def _mk(i: int, key: str) -> dict:
        return {
            "index": i + 1,
            "api_key": key,
            "masked_key": ProxyManager._mask(key),
            "current_proxy": "",
            "remaining_uses": 0,
            "reserved_uses": 0,
            "status": "",
            "last_get_ip_at": None,
            "ip_expires_at": None,
            "last_checked_at": None,
            "next_get_new_at": None,
            "last_error": "",
            "endpoint": None,
            "endpoint_host": None,
            "endpoint_port": None,
            "endpoint_username": None,
            "endpoint_password": None,
            "endpoint_display": "",
            "endpoint_expires_at": None,
            "api_status": "",
            "api_message": "",
        }

    @staticmethod
    def _mask(key: str) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}***{key[-4:]}"

    # -- lifecycle -----------------------------------------------------------

    def start(
        self,
        auth_token: str = "",
        new_url: str = "",
        cur_url: str = "",
        uses_per_proxy: int = 4,
        check_interval: int = 5,
    ) -> None:
        if self.is_started:
            self._cancel_monitor()
        from app.config import settings as s

        self._stop_event = asyncio.Event()
        self._versions.clear()
        self._next_idx = 0
        self._uses_per_proxy = uses_per_proxy
        self._check_interval = max(1, check_interval)
        self._auth_token = auth_token
        self._new_url = new_url or s.KIOT_NEW_URL
        self._cur_url = cur_url or s.KIOT_CURRENT_URL
        for st in self._states:
            st["status"] = "Starting"
            st["last_error"] = ""
        self._monitor_task = asyncio.ensure_future(self._monitor_loop())

    async def stop_async(self) -> None:
        self._cancel_monitor()
        async with self._lock:
            self._next_idx = 0
            self._states.clear()
            if self._monitor_task:
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
                self._monitor_task = None

    def _cancel_monitor(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._stop_event = None
        self._monitor_task = None

    # -- lease acquisition ---------------------------------------------------

    async def try_acquire_async(self) -> Optional[ProxyLease]:
        if not self._states or self._stopped():
            return None
        async with self._lock:
            n = len(self._states)
            for offset in range(n):
                idx = (self._next_idx + offset) % n
                st = self._states[idx]
                if not _ok(st):
                    continue
                st["reserved_uses"] += 1
                self._next_idx = (idx + 1) % n
                return ProxyLease(self, st, st["endpoint"])
            return None

    async def acquire(self, stop_evt: asyncio.Event) -> ProxyLease:
        while not stop_evt.is_set():
            lease = await self.try_acquire_async()
            if lease:
                return lease
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
        raise asyncio.CancelledError()

    async def acquire_for_task(self, stop_evt: asyncio.Event) -> Optional[ProxyLease]:
        return await self.acquire(stop_evt) if self.is_started else None

    # -- lease completion ----------------------------------------------------

    async def _complete(self, state: dict, *, consumed: bool) -> None:
        needs_new = False
        async with self._lock:
            cur = next(
                (s for s in self._states if s["api_key"] == state["api_key"]),
                None,
            )
            if cur is None:
                return
            cur["reserved_uses"] = max(0, cur["reserved_uses"] - 1)
            if consumed:
                cur["remaining_uses"] = max(0, cur["remaining_uses"] - 1)
            needs_new = (
                cur["remaining_uses"] <= 0
                and self.is_started
                and not self._stopped()
            )
            if needs_new:
                cur["status"] = "GettingNew"
                cur["last_error"] = ""
                cur["next_get_new_at"] = None
        if needs_new:
            asyncio.ensure_future(self._fetch_new(state["api_key"]))

    # -- snapshot ------------------------------------------------------------

    def snapshot(self) -> list[dict]:
        return [
            {
                "id": s.get("index", 0),
                "api_key": s["api_key"],
                "masked_api_key": s["masked_key"],
                "current_proxy": s["current_proxy"],
                "remaining_uses": s["remaining_uses"],
                "reserved_uses": s["reserved_uses"],
                "status": s["status"],
                "last_get_ip_at": _dt(s["last_get_ip_at"]),
                "ip_expires_at": _dt(s["ip_expires_at"]),
                "last_checked_at": _dt(s["last_checked_at"]),
                "next_get_new_at": _dt(s["next_get_new_at"]),
                "last_error": s["last_error"],
                "endpoint_host": s["endpoint_host"],
                "endpoint_port": s["endpoint_port"],
                "endpoint_display": s["endpoint_display"],
                "endpoint_expires_at": _dt(s["endpoint_expires_at"]),
            }
            for s in self._states
        ]

    # -- internal checks -----------------------------------------------------

    @staticmethod
    def _want_new(st: dict, now: datetime) -> bool:
        if st["status"] == "GettingNew":
            return False
        ngn = st.get("next_get_new_at")
        if ngn and now < ngn:
            return False
        return (
            st["endpoint"] is None
            or st["remaining_uses"] <= 0
            or _expired(st)
            or st["status"] in ("Starting", "Error", "Waiting")
        )

    # -- monitor loop --------------------------------------------------------

    async def _monitor_loop(self) -> None:
        assert self._stop_event is not None
        try:
            while not self._stop_event.is_set():
                try:
                    await self._check_existing()
                    now = datetime.now()
                    async with self._lock:
                        keys = [
                            s["api_key"]
                            for s in self._states
                            if _want_new(s, now)
                        ]
                    for key in keys:
                        if self._stopped():
                            break
                        await self._fetch_new(key)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._check_interval,
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass

    async def _check_existing(self) -> None:
        if not self._states or self._stopped():
            return
        keys: list[str] = []
        async with self._lock:
            keys = [
                s["api_key"]
                for s in self._states
                if s["status"] == "Ready"
                and s["endpoint"] is not None
                and s["remaining_uses"] > 0
            ]
        for key in keys:
            if self._stopped():
                break
            await self._check_one(key)

    async def _check_one(self, api_key: str) -> None:
        try:
            ep = await _KiotProxyClient_instance.get_current_proxy(
                api_key,
                self._auth_token,
                self._cur_url,
                timeout=KIOT_TIMEOUT_S,
            )
            async with self._lock:
                st = next(
                    (s for s in self._states if s["api_key"] == api_key),
                    None,
                )
                if st is None or st["status"] == "GettingNew":
                    return
                _apply(st, ep)
                st["last_checked_at"] = datetime.now()
                st["status"] = "Ready"
                st["last_error"] = ep.api_message or ""
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            self._schedule_set_err(
                api_key,
                f"Quá {KIOT_TIMEOUT_S}s chưa kiểm tra được proxy.",
            )
        except Exception as ex:
            self._schedule_set_err(api_key, str(ex))

    async def _fetch_new(self, api_key: str) -> None:
        ver = await self._begin_new(api_key)
        if ver == 0:
            return
        try:
            ep = await _KiotProxyClient_instance.get_new_proxy(
                api_key,
                self._auth_token,
                self._new_url,
                timeout=KIOT_TIMEOUT_S,
            )
            async with self._lock:
                st = next(
                    (s for s in self._states if s["api_key"] == api_key),
                    None,
                )
                if st is None or not self._same_ver(api_key, ver):
                    return
                _apply(st, ep)
                st["remaining_uses"] = max(1, self._uses_per_proxy)
                st["reserved_uses"] = 0
                st["status"] = "Ready"
                st["last_get_ip_at"] = datetime.now()
                st["ip_expires_at"] = (
                    ep.expires_at or datetime.now() + IP_LIFETIME
                )
                st["last_error"] = ep.api_message or ""
                st["next_get_new_at"] = None
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            if self._same_ver(api_key, ver):
                self._schedule_set_wait(
                    api_key,
                    f"Quá {KIOT_TIMEOUT_S}s chưa lấy được IP, gọi lấy IP mới lại.",
                    timedelta(seconds=1),
                )
        except RuntimeError as ex:
            if self._same_ver(api_key, ver):
                delay = _retry_delay(str(ex))
                self._schedule_set_wait(api_key, str(ex), delay)

    # -- version guards -------------------------------------------------------

    async def _begin_new(self, api_key: str) -> int:
        """Async version — always called from async context."""
        async with self._lock:
            st = next(
                (s for s in self._states if s["api_key"] == api_key),
                None,
            )
            if st is None:
                return 0
            ver = self._versions.get(api_key, 0) + 1
            self._versions[api_key] = ver
            st["status"] = "GettingNew"
            st["last_error"] = ""
            st["next_get_new_at"] = None
            return ver

    def _same_ver(self, api_key: str, ver: int) -> bool:
        return self._versions.get(api_key, 0) == ver

    def _schedule_set_err(self, api_key: str, error: str) -> None:
        """Schedule an error state update via ensure_future."""
        asyncio.ensure_future(self._do_set_err(api_key, error))

    async def _do_set_err(self, api_key: str, error: str) -> None:
        async with self._lock:
            st = next(
                (s for s in self._states if s["api_key"] == api_key),
                None,
            )
            if st is None or st["status"] == "GettingNew":
                return
            st["last_checked_at"] = datetime.now()
            st["last_error"] = error

    def _schedule_set_wait(self, api_key: str, error: str, delay: Optional[timedelta]) -> None:
        secs = max(1, int(delay.total_seconds())) if delay else random.randint(1, 6)
        asyncio.ensure_future(
            self._do_set_wait(api_key, error, secs)
        )

    async def _do_set_wait(self, api_key: str, error: str, secs: int) -> None:
        async with self._lock:
            st = next(
                (s for s in self._states if s["api_key"] == api_key),
                None,
            )
            if st is None:
                return
            st["status"] = "Waiting"
            st["last_error"] = f"Gửi lại sau {secs}s"
            st["next_get_new_at"] = datetime.now() + timedelta(seconds=secs)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _ok(st: dict) -> bool:
    return (
        st["endpoint"] is not None
        and st["remaining_uses"] > st["reserved_uses"]
        and not (
            st["ip_expires_at"]
            and datetime.now() >= st["ip_expires_at"]
        )
        and st["status"] == "Ready"
    )


def _expired(st: dict) -> bool:
    ep = st.get("ip_expires_at")
    return ep is not None and datetime.now() >= ep


def _want_new(st: dict, now: datetime) -> bool:
    if st["status"] == "GettingNew":
        return False
    ngn = st.get("next_get_new_at")
    if ngn and now < ngn:
        return False
    return (
        st["endpoint"] is None
        or st["remaining_uses"] <= 0
        or _expired(st)
        or st["status"] in ("Starting", "Error", "Waiting")
    )


def _apply(st: dict, ep: ProxyEndpointData) -> None:
    st["endpoint"] = ep
    st["endpoint_host"] = ep.host
    st["endpoint_port"] = ep.http_port
    st["endpoint_username"] = ep.username
    st["endpoint_password"] = ep.password
    st["endpoint_display"] = ep.display
    st["endpoint_expires_at"] = ep.expires_at
    st["current_proxy"] = ep.display


def _dt(d) -> Optional[str]:
    return d.isoformat() if d else None


def _retry_delay(msg: str) -> Optional[timedelta]:
    import re
    m = re.search(
        r"(?:Gửi lại sau|Gui lai sau|retry after|try again in)"
        r"\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?",
        msg,
        re.IGNORECASE,
    )
    if m:
        try:
            return timedelta(seconds=int(m.group(1)))
        except ValueError:
            pass
    return None
