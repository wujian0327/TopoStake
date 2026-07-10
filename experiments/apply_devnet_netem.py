#!/usr/bin/env python3
"""Apply Linux tc/netem delay to Kurtosis devnet containers."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class Container:
    name: str
    pid: int
    labels: dict[str, str]


def run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    return result.stdout


def kurtosis_services(enclave: str) -> list[str]:
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = "/tmp/kurtosis-data"
    result = subprocess.run(
        ["kurtosis", "enclave", "inspect", enclave],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    services = []
    service_re = re.compile(r"^[0-9a-f]{12}\s+(\S+)\s+")
    for line in result.stdout.splitlines():
        match = service_re.match(line)
        if match:
            services.append(match.group(1))
    return services


def docker_containers() -> list[Container]:
    raw_ids = run(["docker", "ps", "-q"]).splitlines()
    if not raw_ids:
        return []
    raw = run(["docker", "inspect", *raw_ids])
    inspected: list[dict[str, Any]] = json.loads(raw)
    containers = []
    for item in inspected:
        state = item.get("State", {})
        pid = int(state.get("Pid") or 0)
        if pid <= 0:
            continue
        containers.append(
            Container(
                name=str(item.get("Name", "")).lstrip("/"),
                pid=pid,
                labels={str(k): str(v) for k, v in item.get("Config", {}).get("Labels", {}).items()},
            )
        )
    return containers


def matches_service(container: Container, service: str, enclave: str) -> bool:
    if service in container.name and enclave in container.name:
        return True
    haystack = " ".join([container.name, *container.labels.keys(), *container.labels.values()])
    return service in haystack and enclave in haystack


def selected_containers(enclave: str, roles: set[str]) -> list[Container]:
    services = [
        service
        for service in kurtosis_services(enclave)
        if ("el" in roles and service.startswith("el-"))
        or ("cl" in roles and service.startswith("cl-"))
        or ("vc" in roles and service.startswith("vc-"))
    ]
    containers = docker_containers()
    selected = []
    missing = []
    for service in services:
        matches = [container for container in containers if matches_service(container, service, enclave)]
        if matches:
            selected.append(matches[0])
        else:
            missing.append(service)
    if missing:
        raise RuntimeError(f"failed to map services to docker containers: {', '.join(missing)}")
    deduped = {container.name: container for container in selected}
    return [deduped[name] for name in sorted(deduped)]


def netem_args(delay_ms: int, jitter_ms: int, loss_pct: float) -> list[str]:
    delay = f"{delay_ms}ms"
    args = ["delay", delay]
    if jitter_ms > 0:
        args.append(f"{jitter_ms}ms")
    if loss_pct > 0:
        args.extend(["loss", f"{loss_pct}%"])
    return args


def run_in_netns(container: Container, tc_args: list[str], dry_run: bool) -> str:
    command = [
        "sudo",
        "-n",
        "nsenter",
        "-t",
        str(container.pid),
        "-n",
        "tc",
        *tc_args,
    ]
    if dry_run:
        return " ".join(command)
    return run(command).strip()


def apply_interface_netem(container: Container, delay_ms: int, jitter_ms: int, loss_pct: float, dry_run: bool) -> None:
    command = [
        "qdisc",
        "replace",
        "dev",
        "eth0",
        "root",
        "netem",
        *netem_args(delay_ms, jitter_ms, loss_pct),
    ]
    output = run_in_netns(container, command, dry_run)
    if dry_run:
        print(output)


def clear_netem(container: Container, dry_run: bool) -> None:
    command = ["qdisc", "del", "dev", "eth0", "root"]
    try:
        output = run_in_netns(container, command, dry_run)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 2:
            return
        raise
    if dry_run:
        print(output)


def apply_p2p_port_netem(
    container: Container,
    delay_ms: int,
    jitter_ms: int,
    loss_pct: float,
    p2p_port: int,
    dry_run: bool,
) -> None:
    commands = [
        ["qdisc", "replace", "dev", "eth0", "root", "handle", "1:", "prio", "bands", "3"],
        [
            "qdisc",
            "replace",
            "dev",
            "eth0",
            "parent",
            "1:3",
            "handle",
            "30:",
            "netem",
            *netem_args(delay_ms, jitter_ms, loss_pct),
        ],
        [
            "filter",
            "add",
            "dev",
            "eth0",
            "protocol",
            "ip",
            "parent",
            "1:",
            "prio",
            "1",
            "u32",
            "match",
            "ip",
            "dport",
            str(p2p_port),
            "0xffff",
            "flowid",
            "1:3",
        ],
        [
            "filter",
            "add",
            "dev",
            "eth0",
            "protocol",
            "ip",
            "parent",
            "1:",
            "prio",
            "2",
            "u32",
            "match",
            "ip",
            "sport",
            str(p2p_port),
            "0xffff",
            "flowid",
            "1:3",
        ],
    ]
    for command in commands:
        output = run_in_netns(container, command, dry_run)
        if dry_run:
            print(output)


def show_qdisc(container: Container, dry_run: bool) -> str:
    command = [
        "sudo",
        "-n",
        "nsenter",
        "-t",
        str(container.pid),
        "-n",
        "tc",
        "qdisc",
        "show",
        "dev",
        "eth0",
    ]
    if dry_run:
        return " ".join(command)
    return run(command).strip()


def show_filter(container: Container, dry_run: bool) -> str:
    command = [
        "sudo",
        "-n",
        "nsenter",
        "-t",
        str(container.pid),
        "-n",
        "tc",
        "filter",
        "show",
        "dev",
        "eth0",
    ]
    if dry_run:
        return " ".join(command)
    return run(command).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enclave", required=True)
    parser.add_argument("--delay-ms", type=int, required=True)
    parser.add_argument("--jitter-ms", type=int, default=0)
    parser.add_argument("--loss-pct", type=float, default=0.0)
    parser.add_argument("--roles", default="el,cl", help="Comma-separated service prefixes: el,cl,vc")
    parser.add_argument(
        "--mode",
        choices=["interface", "p2p-port", "clear"],
        default="interface",
        help="interface delays all eth0 traffic; p2p-port delays only traffic with source or destination P2P port",
    )
    parser.add_argument("--p2p-port", type=int, default=30303)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    roles = {role.strip() for role in args.roles.split(",") if role.strip()}
    containers = selected_containers(args.enclave, roles)
    for container in containers:
        if args.mode == "clear":
            clear_netem(container, args.dry_run)
        elif args.mode == "p2p-port":
            apply_p2p_port_netem(
                container,
                args.delay_ms,
                args.jitter_ms,
                args.loss_pct,
                args.p2p_port,
                args.dry_run,
            )
        else:
            apply_interface_netem(container, args.delay_ms, args.jitter_ms, args.loss_pct, args.dry_run)
    print(
        f"applied netem mode={args.mode} delay={args.delay_ms}ms jitter={args.jitter_ms}ms "
        f"loss={args.loss_pct}% roles={','.join(sorted(roles))} containers={len(containers)}"
    )
    for container in containers[: min(5, len(containers))]:
        print(f"{container.name}: {show_qdisc(container, args.dry_run)}")
        if args.mode == "p2p-port":
            print(show_filter(container, args.dry_run))


if __name__ == "__main__":
    main()
