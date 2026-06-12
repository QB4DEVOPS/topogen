#!/usr/bin/env python3
"""Shared NaC mgmt host sync helpers for DHCP (IPv4) and SLAAC (IPv6) scripts."""

from __future__ import annotations

from pathlib import Path

import yaml

ROUTER_NODE_DEFINITIONS = frozenset({"csr1000v", "iosv"})


def mgmt_interface_name(node_definition: str, mgmt_slot: int) -> str:
    if node_definition == "iosv":
        return f"GigabitEthernet0/{mgmt_slot}"
    return f"GigabitEthernet{mgmt_slot}"


def canonical_name(index: int) -> str:
    return f"iosv-{index:02d}"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def dump_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def patch_nac_files(nac_root: Path, mapping: dict[str, str]) -> None:
    nac_yaml = nac_root / "nac.yaml"
    inventory_yaml = nac_root / "inventory.yaml"
    devices_yaml = nac_root / "devices.yaml"

    nac_data = load_yaml(nac_yaml)
    for device in nac_data.get("iosxe", {}).get("devices", []):
        name = device.get("name", "")
        if name in mapping:
            device["host"] = mapping[name]
    dump_yaml(nac_yaml, nac_data)

    inv_data = load_yaml(inventory_yaml)
    host_groups: list[dict] = []
    all_block = inv_data.get("all", {})
    if isinstance(all_block.get("hosts"), dict):
        host_groups.append(all_block["hosts"])
    for group in all_block.get("children", {}).values():
        if isinstance(group, dict) and isinstance(group.get("hosts"), dict):
            host_groups.append(group["hosts"])
    for hosts in host_groups:
        for host_name, host_vars in hosts.items():
            if host_name in mapping and isinstance(host_vars, dict):
                host_vars["ansible_host"] = mapping[host_name]
    dump_yaml(inventory_yaml, inv_data)

    dev_data = load_yaml(devices_yaml)
    for device in dev_data.get("devices", []):
        name = device.get("name", "")
        if name in mapping:
            device["mgmt_ip"] = mapping[name]
    dump_yaml(devices_yaml, dev_data)
