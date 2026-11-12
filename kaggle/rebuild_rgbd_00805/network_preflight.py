#!/usr/bin/env python3
"""Check Kaggle DNS and outbound TCP access needed by the pinned bootstrap."""
from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Callable, Iterable


BOOTSTRAP_HOSTS = (
    "micro.mamba.pm",
    "conda.anaconda.org",
    "pypi.org",
    "files.pythonhosted.org",
    "download.pytorch.org",
)


def _connect_addrinfo(address: tuple, timeout_s: float) -> None:
    family, socktype, proto, _canonname, sockaddr = address
    with socket.socket(family, socktype, proto) as connection:
        connection.settimeout(timeout_s)
        connection.connect(sockaddr)


def probe_hosts(
    hosts: Iterable[str] = BOOTSTRAP_HOSTS,
    *,
    timeout_s: float = 2.0,
    resolver: Callable = socket.getaddrinfo,
    connector: Callable = _connect_addrinfo,
) -> list[dict]:
    """Return one DNS/TCP status record per host without installing anything."""
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    results = []
    for host in hosts:
        try:
            addresses = resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            results.append({"host": host, "ok": False, "stage": "dns", "error": str(exc)})
            continue
        if not addresses:
            results.append({
                "host": host,
                "ok": False,
                "stage": "dns",
                "error": "DNS returned no addresses",
            })
            continue

        errors = []
        for address in addresses:
            try:
                connector(address, timeout_s)
                results.append({"host": host, "ok": True, "stage": "ready"})
                break
            except OSError as exc:
                errors.append(str(exc))
        else:
            results.append({
                "host": host,
                "ok": False,
                "stage": "tcp",
                "error": "; ".join(errors) or "TCP connection failed",
            })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    args = parser.parse_args(argv)
    try:
        results = probe_hosts(timeout_s=args.timeout_s)
    except ValueError as exc:
        parser.error(str(exc))
    report = {"ok": all(row["ok"] for row in results), "results": results}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
