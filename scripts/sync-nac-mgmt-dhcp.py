#!/usr/bin/env python3
"""Sync NaC mgmt hosts from live CML bridge DHCP addresses on GigabitEthernet5/0/5."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from ipaddress import ip_address
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MGMT_IFACE_FILTER = "GigabitEthernet5"
BRIDGE_PREFIX = "192.168.1."
DHCP_FIX_COMMANDS = (
    "interface GigabitEthernet5\n"
    "no ip address\n"
    "ip address dhcp\n"
    "no shutdown"
)
IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _canonical_name(index: int) -> str:
    return f"iosv-{index:02d}"


def _parse_mgmt_ip(output: str) -> str | None:
    for line in output.splitlines():
        if MGMT_IFACE_FILTER not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        candidate = parts[1]
        if candidate == "unassigned":
            continue
        try:
            ip = ip_address(candidate)
        except ValueError:
            continue
        if str(ip).startswith(BRIDGE_PREFIX):
            return str(ip)
    return None


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _dump_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _patch_nac_files(nac_root: Path, mapping: dict[str, str]) -> None:
    nac_yaml = nac_root / "nac.yaml"
    inventory_yaml = nac_root / "inventory.yaml"
    devices_yaml = nac_root / "devices.yaml"

    nac_data = _load_yaml(nac_yaml)
    for device in nac_data.get("iosxe", {}).get("devices", []):
        name = device.get("name", "")
        if name in mapping:
            device["host"] = mapping[name]
    _dump_yaml(nac_yaml, nac_data)

    inv_data = _load_yaml(inventory_yaml)
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
    _dump_yaml(inventory_yaml, inv_data)

    dev_data = _load_yaml(devices_yaml)
    for device in dev_data.get("devices", []):
        name = device.get("name", "")
        if name in mapping:
            device["mgmt_ip"] = mapping[name]
    _dump_yaml(devices_yaml, dev_data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-id", help="CML lab UUID (required unless --mapping-file)")
    parser.add_argument("--nac-root", required=True, type=Path, help="Path to nac/ output tree")
    parser.add_argument(
        "--mapping-file",
        type=Path,
        help="JSON map of iosv-NN -> 192.168.1.x (skip CML polling)",
    )
    parser.add_argument(
        "--fix-dhcp",
        action="store_true",
        help="Push Gi5 DHCP remediation on BOOTED routers before reading addresses",
    )
    parser.add_argument(
        "--mgmt-slot",
        type=int,
        default=5,
        help="CSR mgmt interface slot (default 5 -> GigabitEthernet5)",
    )
    args = parser.parse_args()

    global MGMT_IFACE_FILTER
    MGMT_IFACE_FILTER = f"GigabitEthernet{args.mgmt_slot}"

    if args.mapping_file:
        mapping = json.loads(args.mapping_file.read_text(encoding="utf-8"))
        _patch_nac_files(args.nac_root, mapping)
        report_path = args.nac_root / "mgmt_dhcp_sync.json"
        report_path.write_text(
            json.dumps({"synced": len(mapping), "mapping": mapping}, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"synced": len(mapping), "report": str(report_path)}, indent=2))
        return 0

    if not args.lab_id:
        print("--lab-id is required unless --mapping-file is provided", file=sys.stderr)
        return 1

    try:
        from virl2_client import ClientLibrary
    except ImportError:
        print("virl2_client is required", file=sys.stderr)
        return 1

    url = os.environ.get("VIRL2_URL", "https://192.168.1.183")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    client = ClientLibrary(url, user, password, ssl_verify=False)
    lab = client.join_existing_lab(args.lab_id)

    mapping: dict[str, str] = {}
    report: dict[str, object] = {
        "lab_id": args.lab_id,
        "nac_root": str(args.nac_root),
        "mgmt_interface": MGMT_IFACE_FILTER,
        "routers": {},
    }

    for node in lab.nodes():
        if node.node_definition != "csr1000v":
            continue
        label = node.label
        if not label.startswith("R") or not label[1:].isdigit():
            continue
        index = int(label[1:])
        canonical = _canonical_name(index)
        entry: dict[str, str | None] = {"state": str(node.state), "mgmt_ip": None, "error": None}

        if str(node.state) != "BOOTED":
            report["routers"][label] = entry
            continue

        try:
            if args.fix_dhcp:
                node.run_pyats_config_command(
                    DHCP_FIX_COMMANDS.replace("GigabitEthernet5", MGMT_IFACE_FILTER)
                )
            show_cmd = f"show ip interface brief | include {MGMT_IFACE_FILTER}"
            output = node.run_pyats_command(show_cmd, config=False)
            mgmt_ip = _parse_mgmt_ip(str(output))
            entry["mgmt_ip"] = mgmt_ip
            if mgmt_ip:
                mapping[canonical] = mgmt_ip
        except Exception as exc:  # noqa: BLE001 - surface per-node CML/pyATS failures
            entry["error"] = str(exc)

        report["routers"][label] = entry

    if mapping:
        _patch_nac_files(args.nac_root, mapping)

    report["synced"] = len(mapping)
    report_path = args.nac_root / "mgmt_dhcp_sync.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"synced": len(mapping), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
