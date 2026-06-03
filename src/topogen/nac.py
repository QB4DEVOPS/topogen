# File Chain (see DEVELOPER.md):
# Doc Version: v1.4.0
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


def _normalize_ipv4_host(value) -> str:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""
    if "/" in raw:
        try:
            return str(ip_interface(raw).ip)
        except ValueError:
            return ""
    return raw


def _get_iface_value(iface, key: str, default):
    if isinstance(iface, dict):
        return iface.get(key, default)
    return getattr(iface, key, default)


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
    platform = _platform_from_device_template(device_template)
    interfaces = []
    node_interfaces = getattr(node, "interfaces", None) or []
    sorted_interfaces = sorted(
        node_interfaces,
        key=lambda x: _get_iface_value(x, "slot", 0) if _get_iface_value(x, "slot", None) is not None else 0,
    )
    for iface in sorted_interfaces:
        slot = _get_iface_value(iface, "slot", 0)
        try:
            slot = int(0 if slot is None else slot)
        except (TypeError, ValueError):
            slot = 0
        entry = {
            "name": _interface_label(device_template, slot),
            "slot": slot,
        }
        iface_address = _get_iface_value(iface, "address", None)
        if iface_address:
            entry["ipv4"] = str(iface_address)
        iface_description = _get_iface_value(iface, "description", "")
        if iface_description:
            entry["description"] = str(iface_description)
        interfaces.append(entry)
    loopback = getattr(node, "loopback", None)
    mgmt_ipv4 = _normalize_ipv4_host(loopback.ip if loopback is not None else None)
    loopbacks = []
    if loopback is not None:
        loopbacks.append(
            {
                "name": "Loopback0",
                "ipv4": str(loopback),
            }
        )
    node_id = str(getattr(node, "hostname", ""))

    device = {
        "name": canonical_name,
        "hostname": canonical_name,
        "platform": platform,
        "role": "router",
        "template": template,
        "device_template": device_template,
        "mgmt": {
            # TG-117 fallback: use loopback host IP until explicit mgmt source exists.
            "ipv4": mgmt_ipv4,
        },
        "loopbacks": loopbacks,
        "interfaces": interfaces,
        "metadata": {
            "topogen": {
                "mode": mode,
                "node_id": node_id,
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
        mgmt_ip = _normalize_ipv4_host(device.get("mgmt", {}).get("ipv4", ""))
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


def write_inventory_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Project canonical model into deterministic Ansible inventory.yaml."""
    devices = model.get("iosxe", {}).get("devices", [])
    hosts = {}
    for device in sorted(devices, key=lambda d: d.get("name", "")):
        ansible_host = _normalize_ipv4_host(device.get("mgmt", {}).get("ipv4", ""))
        hosts[device.get("name", "")] = {
            "ansible_host": ansible_host,
            "platform": device.get("platform", ""),
        }
    payload = {"all": {"hosts": hosts}}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            payload,
            handle,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )
    return output_path


def write_group_vars_all_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Project canonical model into deterministic group_vars/all.yaml."""
    devices = sorted(model.get("iosxe", {}).get("devices", []), key=lambda d: d.get("name", ""))
    platform = devices[0].get("platform", "") if devices else ""
    payload = {
        "nac_platform": platform,
        "nac_device_count": len(devices),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            payload,
            handle,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )
    return output_path


def write_host_vars_yaml(model: dict, host_vars_root: Path, overwrite: bool = False) -> list[Path]:
    """Project canonical model into deterministic host_vars/<device>.yaml files."""
    host_vars_root.mkdir(parents=True, exist_ok=True)
    devices = sorted(model.get("iosxe", {}).get("devices", []), key=lambda d: d.get("name", ""))
    written_paths: list[Path] = []
    for device in devices:
        out_path = host_vars_root / f"{device.get('name', '')}.yaml"
        if out_path.exists() and not overwrite:
            raise TopogenError(
                f"Refusing to overwrite existing file: {out_path}. Use --overwrite to replace it."
            )
        payload = {
            "hostname": device.get("hostname", ""),
            "role": device.get("role", ""),
            "template": device.get("template", ""),
            "device_template": device.get("device_template", ""),
            "loopbacks": device.get("loopbacks", []),
            "interfaces": device.get("interfaces", []),
        }
        with out_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                payload,
                handle,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=False,
            )
        written_paths.append(out_path)
    return written_paths


def write_devices_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Project canonical model into deterministic devices.yaml."""
    devices = sorted(model.get("iosxe", {}).get("devices", []), key=lambda d: d.get("name", ""))
    projected_devices = []
    for device in devices:
        mgmt_ip = _normalize_ipv4_host(device.get("mgmt", {}).get("ipv4", ""))
        projected_devices.append(
            {
                "name": device.get("name", ""),
                "hostname": device.get("hostname", ""),
                "platform": device.get("platform", ""),
                "role": device.get("role", ""),
                "mgmt_ip": mgmt_ip,
            }
        )
    payload = {"devices": projected_devices}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            payload,
            handle,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )
    return output_path


def write_nac_metadata_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Write deterministic nac_metadata.yaml for canonical outputs."""
    devices = sorted(model.get("iosxe", {}).get("devices", []), key=lambda d: d.get("name", ""))
    host_vars_artifacts = [f"host_vars/{d.get('name', '')}.yaml" for d in devices]
    generated_artifacts = [
        "nac.yaml",
        "terraform.tfvars.json",
        "inventory.yaml",
        "group_vars/all.yaml",
        *host_vars_artifacts,
        "devices.yaml",
        "nac_metadata.yaml",
    ]
    payload = {
        "schema": "iosxe-one-router-golden-contract",
        "schema_version": "1.0.0",
        "canonical_root": "iosxe.devices[0]",
        "generator": "topogen",
        "ticket_ref": "TG-122",
        "generated_artifacts": generated_artifacts,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            payload,
            handle,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
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
    write_inventory_yaml(
        model,
        nac_root / "inventory.yaml",
        overwrite=overwrite,
    )
    write_group_vars_all_yaml(
        model,
        nac_root / "group_vars" / "all.yaml",
        overwrite=overwrite,
    )
    write_host_vars_yaml(
        model,
        nac_root / "host_vars",
        overwrite=overwrite,
    )
    write_devices_yaml(
        model,
        nac_root / "devices.yaml",
        overwrite=overwrite,
    )
    write_nac_metadata_yaml(
        model,
        nac_root / "nac_metadata.yaml",
        overwrite=overwrite,
    )
    return nac_yaml_path
