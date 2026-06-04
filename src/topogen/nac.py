# File Chain (see DEVELOPER.md):
# Doc Version: v1.8.0
# Date Modified: 2026-06-03
#
# - Called by: src/topogen/render.py (offline simple --nac flow)
# - Reads from: TopogenNode/TopogenInterface objects, render context (mode/template/device-template)
# - Writes to: canonical nac.yaml under offline NaC output root
# - Calls into: yaml.safe_dump, pathlib.Path
#
# Purpose: Build and write canonical NaC output for one-router IOS-XE MVP.
# Blast Radius: Medium - affects NaC offline artifact generation when --nac is enabled.

from ipaddress import ip_interface
from pathlib import Path

import yaml

from topogen.models import TopogenError, TopogenNode


TERRAFORM_MAIN_TF = """# Run Terraform from this nac/ directory so yaml_directories = [\".\"] resolves
# to the directory containing both main.tf and nac.yaml. From the lab root, use:
# terraform -chdir=<lab>/nac <command>

module \"iosxe\" {
  source           = \"netascode/nac-iosxe/iosxe\"
  version          = \"0.1.0\"
  yaml_directories = [\".\"]
}

provider \"iosxe\" {
  # The CiscoDevNet/iosxe provider reads IOSXE_URL, IOSXE_USERNAME, and
  # IOSXE_PASSWORD (or its documented IOSXE_* environment variables).
  # Do not put lab URLs, usernames, or passwords in Terraform files.
  #
  # LAB ONLY: insecure disables TLS certificate verification; acceptable only
  # for throwaway lab gear with self-signed certificates. Never use this for
  # production NaC.
  insecure = true
}
"""


TERRAFORM_VERSIONS_TF = """terraform {
  required_version = \">= 1.8.0\"

  required_providers {
    iosxe = {
      source  = \"CiscoDevNet/iosxe\"
      version = \"0.15.0\"
    }
  }
}
"""


TERRAFORM_TFVARS_EXAMPLE = """# This scaffold is intentionally driven by nac.yaml through yaml_directories = [\".\"].
# Supply provider connection settings with environment variables on your runner.
#
# Bash:
#   export IOSXE_URL=\"https://<lab-device-url>\"
#   export IOSXE_USERNAME=\"<lab-username>\"
#   export IOSXE_PASSWORD=\"<lab-password>\"
#
# PowerShell:
#   $env:IOSXE_URL = \"https://<lab-device-url>\"
#   $env:IOSXE_USERNAME = \"<lab-username>\"
#   $env:IOSXE_PASSWORD = \"<lab-password>\"
"""


TERRAFORM_GITIGNORE = """.terraform/
*.tfstate*
terraform.tfvars
"""


ANSIBLE_CFG = """[defaults]
inventory = inventory.yaml
# LAB ONLY: disables SSH host key checks for disposable CML labs.
host_key_checking = False
retry_files_enabled = False
"""


VERIFY_REACHABILITY_YAML = """---
- name: Verify IOS-XE reachability with read-only facts
  hosts: all
  gather_facts: false
  tasks:
    - name: Gather minimal IOS-XE facts
      cisco.ios.ios_facts:
        gather_subset:
          - min
"""


INFORMATIONAL_NAC_NOTE = (
    "Informational only. NOT a Terraform input. The netascode/nac-iosxe module "
    "is driven solely by nac.yaml via yaml_directories."
)


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


def _split_interface_label(label: str) -> tuple[str, str]:
    for prefix in ("GigabitEthernet",):
        if label.startswith(prefix):
            return prefix, label[len(prefix):]
    return label, ""


def _platform_from_device_template(device_template: str) -> str:
    if device_template in {"iosv", "csr1000v"}:
        return "iosxe"
    raise TopogenError(
        "NaC canonical writer supports IOS-XE templates only "
        f"(iosv, csr1000v); received {device_template}"
    )


def _canonical_name_for_index(index: int) -> str:
    return f"iosv-{index:02d}"


def _as_nodes(node_or_nodes) -> list[TopogenNode]:
    if isinstance(node_or_nodes, list):
        return node_or_nodes
    return [node_or_nodes]


def _select_host(node: TopogenNode, args) -> str:
    """Select connection host from model data, never from Loopback0."""
    node_interfaces = getattr(node, "interfaces", None) or []
    if bool(getattr(args, "enable_mgmt", False)):
        for iface in node_interfaces:
            description = str(_get_iface_value(iface, "description", ""))
            if description == "OOB Management":
                return _normalize_ipv4_host(_get_iface_value(iface, "address", None))
        return ""

    data_interfaces = sorted(
        node_interfaces,
        key=lambda iface: _get_iface_value(iface, "slot", 0)
        if _get_iface_value(iface, "slot", None) is not None
        else 0,
    )
    for iface in data_interfaces:
        slot = _get_iface_value(iface, "slot", None)
        try:
            slot = int(0 if slot is None else slot)
        except (TypeError, ValueError):
            slot = 0
        if slot == 0:
            return _normalize_ipv4_host(_get_iface_value(iface, "address", None))
    return ""


def _ipv4_mapping(address) -> dict:
    iface = ip_interface(address)
    return {
        "address": str(iface.ip),
        "address_mask": str(iface.netmask),
    }


def build_canonical_nac_model(
    node: TopogenNode | list[TopogenNode],
    *,
    device_template: str,
    template: str,
    mode: str,
    args=None,
) -> dict:
    """Build canonical NaC model rooted at iosxe.devices[*]."""
    platform = _platform_from_device_template(device_template)
    devices = []
    nodes = _as_nodes(node)
    for index, node_obj in enumerate(nodes, start=1):
        canonical_name = _canonical_name_for_index(index)
        system_hostname = str(getattr(node_obj, "hostname", ""))
        interfaces = []
        ethernets = []
        vrf_names = set()
        node_interfaces = getattr(node_obj, "interfaces", None) or []
        sorted_interfaces = sorted(
            node_interfaces,
            key=lambda x: _get_iface_value(x, "slot", 0)
            if _get_iface_value(x, "slot", None) is not None
            else 0,
        )
        for iface in sorted_interfaces:
            slot = _get_iface_value(iface, "slot", 0)
            try:
                slot = int(0 if slot is None else slot)
            except (TypeError, ValueError):
                slot = 0
            iface_label = _interface_label(device_template, slot)
            entry = {
                "name": iface_label,
                "slot": slot,
            }
            iface_type, iface_id = _split_interface_label(iface_label)
            ethernet_entry = {
                "type": iface_type,
                "id": str(iface_id),
            }
            iface_address = _get_iface_value(iface, "address", None)
            if iface_address:
                entry["ipv4"] = str(iface_address)
                ethernet_entry["ipv4"] = _ipv4_mapping(iface_address)
            iface_description = _get_iface_value(iface, "description", "")
            if iface_description:
                entry["description"] = str(iface_description)
                ethernet_entry["description"] = str(iface_description)
            iface_vrf = _get_iface_value(iface, "vrf", None)
            if iface_vrf:
                entry["vrf"] = str(iface_vrf)
                ethernet_entry["vrf_forwarding"] = str(iface_vrf)
                vrf_names.add(str(iface_vrf))
            interfaces.append(entry)
            if iface_address:
                ethernets.append(ethernet_entry)
        loopback = getattr(node_obj, "loopback", None)
        host = _select_host(node_obj, args)
        loopbacks = []
        config_loopbacks = []
        if loopback is not None:
            loopbacks.append(
                {
                    "name": "Loopback0",
                    "ipv4": str(loopback),
                }
            )
            config_loopbacks.append(
                {
                    "id": "0",
                    "ipv4": _ipv4_mapping(loopback),
                }
            )
        configuration = {
            "system": {
                "hostname": system_hostname,
            }
        }
        if vrf_names:
            configuration["vrfs"] = [{"name": name} for name in sorted(vrf_names)]
        config_interfaces = {}
        if ethernets:
            config_interfaces["ethernets"] = ethernets
        if config_loopbacks:
            config_interfaces["loopbacks"] = config_loopbacks
        if config_interfaces:
            configuration["interfaces"] = config_interfaces
        devices.append(
            {
                "name": canonical_name,
                "host": host,
                "configuration": configuration,
                "hostname": system_hostname,
                "platform": platform,
                "role": "router",
                "template": template,
                "device_template": device_template,
                "mgmt": {
                    "ipv4": host,
                },
                "loopbacks": loopbacks,
                "interfaces": interfaces,
                "metadata": {
                    "topogen": {
                        "mode": mode,
                        "node_id": system_hostname,
                        "name_source": "synthetic inventory name",
                        "hostname_source": "TopogenNode.hostname",
                    }
                },
            }
        )
    devices = sorted(devices, key=lambda d: d.get("name", ""))
    return {
        "iosxe": {
            "devices": devices
        }
    }


def _has_real_value(value) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_has_real_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_real_value(item) for item in value.values())
    return True


def _prune_empty_values(value):
    if isinstance(value, list):
        pruned = [_prune_empty_values(item) for item in value]
        return [item for item in pruned if _has_real_value(item)]
    if isinstance(value, dict):
        pruned = {}
        for key, item in value.items():
            next_value = _prune_empty_values(item)
            if _has_real_value(next_value):
                pruned[key] = next_value
        return pruned
    return value


def project_nac_yaml(model: dict) -> dict:
    """Project the fat canonical model into the confirmed lean nac.yaml schema."""
    devices = []
    for device in model.get("iosxe", {}).get("devices", []):
        projected_device = {}
        name = device.get("name")
        if _has_real_value(name):
            projected_device["name"] = name
        host = device.get("host")
        if _has_real_value(host):
            projected_device["host"] = host
        configuration = _prune_empty_values(device.get("configuration", {}))
        if _has_real_value(configuration):
            projected_device["configuration"] = configuration
        if _has_real_value(projected_device):
            devices.append(projected_device)
    return {
        "iosxe": {
            "devices": devices
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
            project_nac_yaml(model),
            handle,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )
    return output_path


def _write_static_text(output_path: Path, content: str, overwrite: bool = False) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise TopogenError(
            f"Refusing to overwrite existing file: {output_path}. Use --overwrite to replace it."
        )
    output_path.write_text(content, encoding="utf-8")
    return output_path


def write_terraform_main_tf(output_path: Path, overwrite: bool = False) -> Path:
    """Write the static netascode/nac-iosxe module scaffold."""
    return _write_static_text(output_path, TERRAFORM_MAIN_TF, overwrite=overwrite)


def write_terraform_versions_tf(output_path: Path, overwrite: bool = False) -> Path:
    """Write the Terraform/provider version pins required by nac-iosxe 0.1.0."""
    return _write_static_text(output_path, TERRAFORM_VERSIONS_TF, overwrite=overwrite)


def write_terraform_tfvars_example(output_path: Path, overwrite: bool = False) -> Path:
    """Write placeholder-only provider environment variable guidance."""
    return _write_static_text(output_path, TERRAFORM_TFVARS_EXAMPLE, overwrite=overwrite)


def write_terraform_gitignore(output_path: Path, overwrite: bool = False) -> Path:
    """Write Terraform local-state ignore rules for the nac workspace."""
    return _write_static_text(output_path, TERRAFORM_GITIGNORE, overwrite=overwrite)


def write_terraform_scaffold(nac_root: Path, overwrite: bool = False) -> list[Path]:
    """Write the static Terraform scaffold files under nac_root."""
    return [
        write_terraform_main_tf(nac_root / "main.tf", overwrite=overwrite),
        write_terraform_versions_tf(nac_root / "versions.tf", overwrite=overwrite),
        write_terraform_tfvars_example(nac_root / "terraform.tfvars.example", overwrite=overwrite),
        write_terraform_gitignore(nac_root / ".gitignore", overwrite=overwrite),
    ]


def write_ansible_cfg(output_path: Path, overwrite: bool = False) -> Path:
    """Write the parse-only Ansible config stub."""
    return _write_static_text(output_path, ANSIBLE_CFG, overwrite=overwrite)


def write_verify_reachability_yaml(output_path: Path, overwrite: bool = False) -> Path:
    """Write the read-only Ansible ios_facts smoke playbook."""
    return _write_static_text(output_path, VERIFY_REACHABILITY_YAML, overwrite=overwrite)


def write_inventory_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Project canonical model into deterministic Ansible inventory.yaml."""
    devices = model.get("iosxe", {}).get("devices", [])
    hosts = {}
    for device in sorted(devices, key=lambda d: d.get("name", "")):
        ansible_host = _normalize_ipv4_host(device.get("host") or device.get("mgmt", {}).get("ipv4", ""))
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
        "ansible_connection": "ansible.netcommon.network_cli",
        "ansible_network_os": "cisco.ios.ios",
        "ansible_user": "{{ lookup('env', 'IOSXE_USERNAME') }}",
        "ansible_password": "{{ lookup('env', 'IOSXE_PASSWORD') }}",
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
        mgmt_ip = _normalize_ipv4_host(device.get("host") or device.get("mgmt", {}).get("ipv4", ""))
        projected_devices.append(
            {
                "name": device.get("name", ""),
                "hostname": device.get("hostname", ""),
                "platform": device.get("platform", ""),
                "role": device.get("role", ""),
                "mgmt_ip": mgmt_ip,
            }
        )
    payload = {
        "terraform_input": False,
        "note": INFORMATIONAL_NAC_NOTE,
        "devices": projected_devices,
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


def write_nac_metadata_yaml(model: dict, output_path: Path, overwrite: bool = False) -> Path:
    """Write deterministic nac_metadata.yaml for canonical outputs."""
    devices = sorted(model.get("iosxe", {}).get("devices", []), key=lambda d: d.get("name", ""))
    first_device = devices[0] if devices else {}
    topogen_metadata = first_device.get("metadata", {}).get("topogen", {})
    host_vars_artifacts = [f"host_vars/{d.get('name', '')}.yaml" for d in devices]
    generated_artifacts = [
        "nac.yaml",
        "main.tf",
        "versions.tf",
        "terraform.tfvars.example",
        ".gitignore",
        "inventory.yaml",
        "ansible.cfg",
        "group_vars/all.yaml",
        *host_vars_artifacts,
        "verify_reachability.yaml",
        "devices.yaml",
        "nac_metadata.yaml",
    ]
    payload = {
        "terraform_input": False,
        "note": INFORMATIONAL_NAC_NOTE,
        "schema": "iosxe-devices-configuration-mvp",
        "schema_version": "3.0.0",
        "canonical_root": "iosxe.devices[]",
        "contract": "lean iosxe.devices[].configuration.*",
        "epic_ref": "TG-131",
        "module": "netascode/nac-iosxe/iosxe 0.1.0",
        "provider": "CiscoDevNet/iosxe 0.15.0",
        "generator": "topogen",
        "mode": topogen_metadata.get("mode", ""),
        "template": first_device.get("template", ""),
        "device_template": first_device.get("device_template", ""),
        "device_count": len(devices),
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
    device_template: str,
    template: str,
    mode: str,
    node: TopogenNode | None = None,
    nodes: list[TopogenNode] | None = None,
    args=None,
    overwrite: bool = False,
) -> Path:
    """Orchestrate canonical NaC output write tree."""
    selected_nodes = nodes if nodes is not None else ([node] if node is not None else [])
    if not selected_nodes:
        raise TopogenError("NaC writer requires at least one router node")
    model = build_canonical_nac_model(
        selected_nodes,
        device_template=device_template,
        template=template,
        mode=mode,
        args=args,
    )
    nac_root.mkdir(parents=True, exist_ok=True)
    nac_yaml_path = write_nac_yaml(model, nac_root / "nac.yaml", overwrite=overwrite)
    write_terraform_scaffold(nac_root, overwrite=overwrite)
    write_ansible_cfg(
        nac_root / "ansible.cfg",
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
    write_verify_reachability_yaml(
        nac_root / "verify_reachability.yaml",
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
