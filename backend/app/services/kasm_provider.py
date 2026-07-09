"""Docker-backed Kasm/KasmVNC session provider."""
from __future__ import annotations

import re
import time
import uuid
from urllib.parse import quote

from app.config import settings

KASM_PORT = "6901/tcp"


class KasmProviderError(RuntimeError):
    pass


def start_kasm_session(session_id: uuid.UUID, user_id: uuid.UUID, account_id: uuid.UUID) -> dict:
    try:
        import docker
    except Exception as exc:
        raise KasmProviderError(f"Docker SDK is not installed: {exc}") from exc

    client = docker.from_env()
    container_name = _container_name(session_id)
    _remove_existing(client, container_name)

    profile_host_path = _profile_host_path(client, user_id, account_id)
    labels = {
        settings.KASM_CONTAINER_LABEL: str(session_id),
        "flowmeta.user_id": str(user_id),
        "flowmeta.facebook_account_id": str(account_id),
    }
    try:
        container = client.containers.run(
            settings.KASM_IMAGE,
            detach=True,
            name=container_name,
            environment={
                "VNC_PW": settings.KASM_VNC_PASSWORD,
                "LAUNCH_URL": "https://www.facebook.com/",
            },
            volumes=[
                f"{profile_host_path}:/kasm_profile_sync:rw",
            ],
            ports={KASM_PORT: None},
            network=settings.KASM_DOCKER_NETWORK,
            shm_size="1g",
            labels=labels,
            remove=False,
        )
        container.reload()
        port = _wait_for_mapped_port(container)
        return {
            "container_name": container.name,
            "provider_url": _provider_url(port),
        }
    except Exception as exc:
        _remove_existing(client, container_name)
        raise KasmProviderError(f"Cannot start Kasm browser session: {exc}") from exc


def stop_kasm_session(container_name: str | None) -> None:
    if not container_name:
        return
    try:
        import docker
    except Exception:
        return
    client = docker.from_env()
    _remove_existing(client, container_name)


def _container_name(session_id: uuid.UUID | str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", str(session_id))
    return f"flowmeta-kasm-{safe}"


def _remove_existing(client, container_name: str) -> None:
    try:
        container = client.containers.get(container_name)
    except Exception:
        return
    try:
        container.remove(force=True)
    except Exception:
        pass


def _profile_host_path(client, user_id: uuid.UUID, account_id: uuid.UUID) -> str:
    try:
        volume = client.volumes.get(settings.KASM_BROWSER_PROFILES_VOLUME)
        mountpoint = str(volume.attrs.get("Mountpoint") or "")
    except Exception as exc:
        raise KasmProviderError(
            f"Cannot inspect browser profile volume {settings.KASM_BROWSER_PROFILES_VOLUME}: {exc}"
        ) from exc
    if not mountpoint:
        raise KasmProviderError(f"Browser profile volume {settings.KASM_BROWSER_PROFILES_VOLUME} has no mountpoint")
    return f"{mountpoint}/{user_id}/{account_id}"


def _mapped_port(container) -> str:
    ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
    bindings = ports.get(KASM_PORT) or []
    if not bindings:
        raise KasmProviderError("Kasm container has no mapped 6901/tcp port")
    return str(bindings[0].get("HostPort") or "")


def _wait_for_mapped_port(container) -> str:
    last_status = ""
    for _ in range(30):
        container.reload()
        last_status = str(container.attrs.get("State", {}).get("Status") or "")
        if last_status == "exited":
            logs = container.logs(tail=40).decode("utf-8", errors="replace")
            raise KasmProviderError(f"Kasm container exited during startup: {logs}")
        try:
            port = _mapped_port(container)
            if port:
                return port
        except KasmProviderError:
            pass
        time.sleep(1)
    raise KasmProviderError(f"Kasm container has no mapped 6901/tcp port after waiting; status={last_status}")


def _provider_url(port: str) -> str:
    credentials = ""
    if settings.KASM_EMBED_CREDENTIALS_IN_URL and settings.KASM_PUBLIC_HOST in {"localhost", "127.0.0.1"}:
        credentials = f"kasm_user:{quote(settings.KASM_VNC_PASSWORD, safe='')}@"
    return f"{settings.KASM_PUBLIC_SCHEME}://{credentials}{settings.KASM_PUBLIC_HOST}:{port}"
