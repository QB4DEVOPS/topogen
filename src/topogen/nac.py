# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-03
#
# - Called by: src/topogen/render.py (offline simple --nac flow)
# - Reads from: TopogenNode/TopogenInterface objects, render context (mode/template/device-template)
# - Writes to: canonical nac.yaml under offline NaC output root
# - Calls into: yaml.safe_dump, pathlib.Path
#
# Purpose: Build and write canonical NaC output for one-router IOS-XE MVP.
# Blast Radius: Medium - affects NaC offline artifact generation when --nac is enabled.

import json
from ipaddress import ip_interface
from pathlib import Path

import yaml

from topogen.models import TopogenError, TopogenNode


def _interface_label(device_template: str, slot: int) -> str:
    if device_template == "csr1000v":
        return f"GigabitEthernet{slot + 1}"
    return f"GigabitEthernet0/{slot}"


def _platform_from_device_template(device_template: str) -> str:
    if device_template in {"iosv", "csr1000v"}:
        return "iosxe"
    raise TopogenError(
        "NaC canonical writer supports IOS-XE templates only "
        f"(iosv, csr1000v); received {device_template}"
    )


def build_canonical_nac_model(
    node: TopogenNode,
    *,
    device_template: str,
    template: str,
    mode: str,
    canonical_name: str = "iosv-01",
) -> dict:
    """Build canonical one-router NaC model rooted at iosxe.devices[0]."""
    if node.loopback is None:
        raise TopogenError("NaC canonical writer requires node.loopback for mgmt fallback")

    platform = _platform_from_device_template(device_template)
    interfaces = []
    for iface in sorted(node.interfaces, key=lambda x: x.slot):
        entry = {
            "name": _interface_label(device_template, iface.slot),
            "slot": iface.slot,
        }
        if iface.address is not None:
            entry["ipv4"] = str(iface.address)
        if iface.description:
            entry["description"] = iface.description
        interfaces.append(entry)

    device = {
        "name": canonical_name,
        "hostname": canonical_name,
        "platform": platform,
        "role": "router",
        "template": template,
        "device_template": device_template,
        "mgmt": {
            # TG-117 fallback: use loopback host IP until explicit mgmt source exists.
            "ipv4": str(node.loopback.ip),
        },
        "loopbacks": [
            {
                "name": "Loopback0",
                "ipv4": str(node.loopback),
            }
        ],
        "interfaces": interfaces,
        "metadata": {
            "topogen": {
                "mode": mode,
                "node_id": node.hostname,
            }
        },
    }
    return {
        "iosxe": {
            "devices": [device]
        }
    }


def write_nac_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Write canonical nac.yaml with deterministic key order."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            model,
            handle,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )
    return output_path


def write_terraform_tfvars_json(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Project canonical model into deterministic terraform.tfvars.json."""
    devices = model.get("iosxe", {}).get("devices", [])
    projected_devices = []
    for device in sorted(devices, key=lambda d: d.get("name", "")):
        mgmt_raw = str(device.get("mgmt", {}).get("ipv4", ""))
        if "/" in mgmt_raw:
            mgmt_ip = str(ip_interface(mgmt_raw).ip)
        else:
            mgmt_ip = mgmt_raw
        projected_devices.append(
            {
                "name": device.get("name", ""),
                "hostname": device.get("hostname", ""),
                "platform": device.get("platform", ""),
                "mgmt_ip": mgmt_ip,
            }
        )

    payload = {"devices": projected_devices}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_nac_tree(
    *,
    nac_root: Path,
    node: TopogenNode,
    device_template: str,
    template: str,
    mode: str,
    overwrite: bool = False,
) -> Path:
    """Orchestrate canonical NaC output write tree."""
    nac_root.mkdir(parents=True, exist_ok=True)
    model = build_canonical_nac_model(
        node,
        device_template=device_template,
        template=template,
        mode=mode,
    )
    nac_yaml_path = write_nac_yaml(model, nac_root / "nac.yaml", overwrite=overwrite)
    write_terraform_tfvars_json(
        model,
        nac_root / "terraform.tfvars.json",
        overwrite=overwrite,
    )
    return nac_yaml_path
