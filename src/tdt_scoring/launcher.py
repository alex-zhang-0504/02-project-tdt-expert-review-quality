from __future__ import annotations

import json
import socket
from collections.abc import Callable, Iterable
from urllib.request import urlopen

from .build_info import BUILD_ID, PROJECT_ID


PortState = str
DEFAULT_PORTS = range(8865, 8900)


def inspect_service(port: int) -> PortState:
    with socket.socket() as client:
        client.settimeout(0.25)
        if client.connect_ex(("127.0.0.1", port)) != 0:
            return "free"

    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return "occupied"
    is_current = (
        payload.get("project_id") == PROJECT_ID
        and payload.get("build_id") == BUILD_ID
    )
    return "current" if is_current else "occupied"


def choose_service_port(
    ports: Iterable[int] = DEFAULT_PORTS,
    inspect: Callable[[int], PortState] = inspect_service,
) -> tuple[str, int]:
    first_free: int | None = None
    for port in ports:
        state = inspect(port)
        if state == "current":
            return "reuse", port
        if state == "free" and first_free is None:
            first_free = port
    if first_free is None:
        raise RuntimeError("本地端口8865至8899均被占用，无法启动打分系统")
    return "launch", first_free


def main() -> None:
    action, port = choose_service_port()
    print(action, port, BUILD_ID)


if __name__ == "__main__":
    main()
