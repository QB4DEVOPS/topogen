#!/usr/bin/env python3
"""Sync NaC mgmt hosts from live CML pyATS IPv6 SLAAC addresses on OOB Gi."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from ipaddress import IPv6Address, ip_address
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from nac_mgmt_sync_lib import (  # noqa: E402
    ROUTER_NODE_DEFINITIONS,
    canonical_name,
    mgmt_interface_name,
    patch_nac_files,
)

IPV6_CANDIDATE_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,7}:|"
    r":(?::[0-9A-Fa-f]{1,4}){1,7}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}|"
    r"[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}|"
    r":(?::[0-9A-Fa-f]{1,4}){1,7}|"
    r"fe80::[0-9A-Fa-f:]+|"
    r"FE80::[0-9A-Fa-f:]+"
    r")(?![0-9A-Fa-f:])",
    re.IGNORECASE,
)

DEFAULT_PYATS_CREDS = {
    "username": "cisco",
    "password": "cisco",
    "enable_password": "cisco",
}


def _is_global_unicast(ip: IPv6Address) -> bool:
    return (
        not ip.is_link_local
        and not ip.is_loopback
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def _normalize_ipv6(raw: str) -> str | None:
    candidate = raw.strip().strip("[]").split("/")[0].split("%")[0]
    try:
        ip = ip_address(candidate)
    except ValueError:
        return None
    if ip.version != 6:
        return None
    return str(ip)


def _extract_ipv6_candidates(text: str) -> list[str]:
    found: list[str] = []
    for match in IPV6_CANDIDATE_RE.finditer(text):
        normalized = _normalize_ipv6(match.group(0))
        if normalized and normalized not in found:
            found.append(normalized)
    return found


def pick_preferred_global(addresses: list[str]) -> str | None:
    globals_: list[str] = []
    for addr in addresses:
        ip = ip_address(addr)
        if isinstance(ip, IPv6Address) and _is_global_unicast(ip):
            globals_.append(addr)
    if not globals_:
        return None
    for prefix in ("2600:", "fd00:"):
        for addr in globals_:
            if addr.lower().startswith(prefix):
                return addr
    return globals_[0]


def _iface_section(output: str, iface_name: str) -> str:
    lines = output.splitlines()
    section: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if not in_section:
            if iface_name in line and (
                stripped.startswith("GigabitEthernet") or stripped.startswith("Gi")
            ):
                in_section = True
                section = [line]
            continue
        if stripped.startswith("GigabitEthernet") and iface_name not in line:
            break
        if stripped.startswith("Gi") and iface_name not in line and "Ethernet" not in iface_name:
            break
        section.append(line)
    return "\n".join(section)


def parse_mgmt_ipv6(output: str, iface_name: str) -> str | None:
    """Parse global SLAAC IPv6 for iface from show ipv6 interface* output."""
    section = _iface_section(output, iface_name)
    if not section:
        for line in output.splitlines():
            if iface_name not in line:
                continue
            if "unassigned" in line.lower():
                continue
            addrs = _extract_ipv6_candidates(line)
            picked = pick_preferred_global(addrs)
            if picked:
                return picked
        return None
    addrs = _extract_ipv6_candidates(section)
    return pick_preferred_global(addrs)


def mgmt_ipv6_from_cml_interface(node, iface_name: str) -> str | None:
    """Read mgmt SLAAC IPv6 from CML L3 address snooping (no local pyATS required)."""
    for iface in node.interfaces():
        if iface.label != iface_name:
            continue
        candidates: list[str] = []
        for source in (
            getattr(iface, "discovered_ipv6", None),
            (getattr(iface, "ip_snooped_info", None) or {}).get("ipv6"),
        ):
            if not source:
                continue
            if isinstance(source, str):
                candidates.append(source)
            else:
                candidates.extend(str(item) for item in source)
        normalized: list[str] = []
        for candidate in candidates:
            normalized_addr = _normalize_ipv6(str(candidate))
            if normalized_addr:
                normalized.append(normalized_addr)
        return pick_preferred_global(normalized)
    return None


def _set_pyats_creds(node, creds: dict[str, str]) -> None:
    node.update({"pyats": creds}, exclude_configurations=True)


def _collect_router_nodes(lab):
    routers = []
    for node in lab.nodes():
        if node.node_definition not in ROUTER_NODE_DEFINITIONS:
            continue
        label = node.label
        if not label.startswith("R") or not label[1:].isdigit():
            continue
        routers.append((int(label[1:]), node))
    routers.sort(key=lambda item: item[0])
    return routers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-id", help="CML lab UUID (required unless --mapping-file)")
    parser.add_argument("--nac-root", required=True, type=Path, help="Path to nac/ output tree")
    parser.add_argument(
        "--mapping-file",
        type=Path,
        help="JSON map of iosv-NN -> IPv6 (skip CML polling)",
    )
    parser.add_argument(
        "--set-pyats-creds",
        action="store_true",
        help="Set cisco/cisco pyATS credentials on BOOTED routers before polling",
    )
    parser.add_argument(
        "--cml-snoop-only",
        action="store_true",
        help="Use CML L3 address snooping only (no local pyATS); default tries pyATS first",
    )
    parser.add_argument(
        "--mgmt-slot",
        type=int,
        default=5,
        help="Mgmt interface slot (default 5 -> Gi0/5 on IOSv)",
    )
    parser.add_argument(
        "--device-template",
        choices=("iosv", "csr1000v"),
        default="iosv",
        help="Router image family for mgmt interface naming (default iosv)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print progress every N routers (0 disables)",
    )
    args = parser.parse_args()

    if args.mapping_file:
        mapping = json.loads(args.mapping_file.read_text(encoding="utf-8"))
        patch_nac_files(args.nac_root, mapping)
        report_path = args.nac_root / "mgmt_ipv6_sync.json"
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
    lab.sync_l3_addresses_if_outdated()

    iface_name = mgmt_interface_name(args.device_template, args.mgmt_slot)
    mapping: dict[str, str] = {}
    report: dict[str, object] = {
        "lab_id": args.lab_id,
        "nac_root": str(args.nac_root),
        "mgmt_interface": iface_name,
        "routers": {},
    }

    routers = _collect_router_nodes(lab)
    total = len(routers)
    processed = 0

    for index, node in routers:
        label = node.label
        canonical = canonical_name(index)
        entry: dict[str, str | None] = {
            "state": str(node.state),
            "mgmt_ipv6": None,
            "source": None,
            "error": None,
        }

        if str(node.state) != "BOOTED":
            report["routers"][label] = entry
            processed += 1
            continue

        mgmt_ipv6: str | None = None
        if not args.cml_snoop_only:
            try:
                if args.set_pyats_creds:
                    _set_pyats_creds(node, DEFAULT_PYATS_CREDS)

                brief_cmd = "show ipv6 interface brief"
                brief_out = str(node.run_pyats_command(brief_cmd, config=False))
                mgmt_ipv6 = parse_mgmt_ipv6(brief_out, iface_name)
                if mgmt_ipv6:
                    entry["source"] = "pyats_brief"
                else:
                    detail_cmd = f"show ipv6 interface {iface_name}"
                    detail_out = str(node.run_pyats_command(detail_cmd, config=False))
                    mgmt_ipv6 = parse_mgmt_ipv6(detail_out, iface_name)
                    if mgmt_ipv6:
                        entry["source"] = "pyats_detail"
            except Exception as exc:  # noqa: BLE001 - surface per-node CML/pyATS failures
                entry["error"] = str(exc) or type(exc).__name__

        if not mgmt_ipv6:
            mgmt_ipv6 = mgmt_ipv6_from_cml_interface(node, iface_name)
            if mgmt_ipv6:
                entry["source"] = "cml_snooped"
                entry["error"] = None

        entry["mgmt_ipv6"] = mgmt_ipv6
        if mgmt_ipv6:
            mapping[canonical] = mgmt_ipv6
        report["routers"][label] = entry

        processed += 1
        if args.progress_every and processed % args.progress_every == 0:
            print(
                f"progress: {processed}/{total} routers polled, {len(mapping)} IPv6 synced",
                file=sys.stderr,
            )

    if mapping:
        patch_nac_files(args.nac_root, mapping)

    report["synced"] = len(mapping)
    report["total_routers"] = total
    report_path = args.nac_root / "mgmt_ipv6_sync.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"synced": len(mapping), "total": total, "report": str(report_path)}, indent=2))
    return 0 if mapping else 1


if __name__ == "__main__":
    raise SystemExit(main())
