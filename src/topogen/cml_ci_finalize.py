#!/usr/bin/env python3
"""Post-sync CI finalize: pyATS aliases, wr mem, lab guide, extract, export YAML."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from topogen.cml_lab_evidence import (
    build_ci_report,
    download_lab_yaml,
    embed_ci_evidence,
    extract_working_configs,
    load_mgmt_sync_report,
)
from topogen.nac_mgmt_sync import _cml_client, _collect_router_nodes, mgmt_interface_name

_LOGGER = logging.getLogger(__name__)


def _slaac_alias_token(mgmt_ipv6: str) -> str:
    """Short stable token from SLAAC address for per-router exec alias names."""
    compact = mgmt_ipv6.strip("[]").replace(":", "")
    return compact[-16:] if len(compact) > 16 else compact


def _alias_lines(jira_key: str, mgmt_iface: str, mgmt_ipv6: str | None) -> list[str]:
    lines = [
        f"alias exec slaac show ipv6 interface {mgmt_iface} | include Global",
        "alias exec uptime show version | include uptime",
    ]
    if mgmt_ipv6:
        token = _slaac_alias_token(mgmt_ipv6)
        lines.append(
            f"alias exec slaac_{token} show ipv6 interface {mgmt_iface} | include {mgmt_ipv6}"
        )
        lines.extend(
            [
                f"interface {mgmt_iface}",
                f" description OOB Mgmt | {jira_key} | {mgmt_ipv6}",
            ]
        )
    return lines


def _config_block(lines: list[str]) -> str:
    return "\n".join(lines)


def _ssh_credentials() -> tuple[str, str]:
    user = os.environ.get("IOSXE_USERNAME", "cisco")
    password = os.environ.get("IOSXE_PASSWORD", "cisco")
    return user, password


def _ssh_push_config(host: str, config_block: str) -> None:
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko required for SSH fallback (pip install paramiko)") from exc

    user, password = _ssh_credentials()
    bracketed = host
    if ":" in host and not host.startswith("["):
        bracketed = f"[{host}]"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        bracketed,
        username=user,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    try:
        shell = client.invoke_shell()
        time.sleep(0.5)
        shell.send("enable\n")
        time.sleep(0.3)
        shell.send(f"{password}\n")
        time.sleep(0.3)
        shell.send("configure terminal\n")
        time.sleep(0.3)
        for line in config_block.splitlines():
            shell.send(line + "\n")
            time.sleep(0.15)
        shell.send("end\n")
        time.sleep(0.3)
        shell.send("write memory\n")
        time.sleep(0.3)
        shell.send("\n")
        time.sleep(2.0)
    finally:
        client.close()


def _push_router_config(node, config_block: str, mgmt_ipv6: str | None) -> None:
    try:
        node.run_pyats_config_command(config_block)
        node.run_pyats_command("write memory", config=False)
        return
    except Exception as pyats_exc:
        if mgmt_ipv6 is None:
            raise pyats_exc
        _ssh_push_config(mgmt_ipv6, config_block)


def apply_ci_aliases_pyats(
    lab,
    *,
    jira_key: str,
    mgmt_slot: int = 5,
    device_template: str = "iosv",
    router_ipv6: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    mgmt_iface = mgmt_interface_name(device_template, mgmt_slot)
    router_ipv6 = router_ipv6 or {}
    result: dict[str, Any] = {"routers": 0, "applied": 0, "saved": 0, "nodes": {}}

    for index, node in _collect_router_nodes(lab):
        label = node.label
        canonical = f"iosv-{index:02d}"
        mgmt_ipv6 = router_ipv6.get(canonical)
        entry: dict[str, Any] = {
            "label": label,
            "mgmt_ipv6": mgmt_ipv6,
            "state": str(getattr(node, "state", "")),
        }
        result["nodes"][label] = entry
        result["routers"] += 1
        if entry["state"] != "BOOTED":
            entry["error"] = f"expected BOOTED, got {entry['state']}"
            continue
        block = _config_block(_alias_lines(jira_key, mgmt_iface, mgmt_ipv6))
        entry["config"] = block
        if dry_run:
            entry["ok"] = True
            result["applied"] += 1
            continue
        try:
            _push_router_config(node, block, mgmt_ipv6)
            entry["ok"] = True
            entry["via"] = "pyats-or-ssh"
            result["applied"] += 1
            entry["saved"] = True
            result["saved"] += 1
        except Exception as exc:
            entry["error"] = str(exc) or type(exc).__name__
            _LOGGER.warning("CI finalize failed on %s: %s", label, entry["error"])
    return result


def build_lab_guide_html(jira_key: str, mgmt_sync: dict[str, Any], mgmt_iface: str) -> str:
    rows = []
    routers = mgmt_sync.get("routers") or {}
    for label in sorted(routers, key=lambda x: int(x[1:]) if x[1:].isdigit() else x):
        row = routers[label]
        ipv6 = row.get("mgmt_ipv6") or row.get("mgmt_ip") or "—"
        alias_hint = ""
        if ipv6 and ipv6 != "—":
            alias_hint = f" — alias <code>slaac_{html.escape(_slaac_alias_token(str(ipv6)))}</code>"
        rows.append(
            f"<li><b>{label}</b> {mgmt_iface}: "
            f"<code>{html.escape(str(ipv6))}</code>{alias_hint}</li>"
        )
    mapping = mgmt_sync.get("mapping") or {}
    if not rows and mapping:
        for name, addr in sorted(mapping.items()):
            alias_hint = f" — alias <code>slaac_{html.escape(_slaac_alias_token(addr))}</code>"
            rows.append(
                f"<li><b>{name}</b> {mgmt_iface}: "
                f"<code>{html.escape(addr)}</code>{alias_hint}</li>"
            )
    body = "\n".join(rows) if rows else "<li>no mgmt addresses synced</li>"
    return (
        f"<h3>TopoGen CI — {html.escape(jira_key)}</h3>"
        f"<p>Post-SLAAC management sync (lab guide)</p>"
        f"<ul>{body}</ul>"
        f"<p>Router exec aliases (all nodes):</p>"
        f"<ul>"
        f"<li><code>slaac</code> → "
        f"<code>show ipv6 interface {html.escape(mgmt_iface)} | include Global</code></li>"
        f"<li><code>uptime</code> → <code>show version | include uptime</code></li>"
        f"<li><code>slaac_&lt;token&gt;</code> → per-router Gi5 address "
        f"(token = last 16 hex chars of SLAAC)</li>"
        f"</ul>"
    )


def _prepend_lab_guide(existing: str, guide_html: str) -> str:
    """Prepend visible lab-guide HTML; keep existing notes/metadata spans intact."""
    if not guide_html:
        return existing or ""
    base = existing or ""
    marker = f"<h3>TopoGen CI —"
    if marker in base:
        return base
    if base and not base.endswith("\n"):
        base += "\n"
    return guide_html + "\n" + base


def set_lab_guide(lab, guide_html: str, *, dry_run: bool = False) -> None:
    existing = getattr(lab, "notes", "") or ""
    notes = _prepend_lab_guide(existing, guide_html)
    if dry_run:
        return
    lab.notes = notes


def finalize_ci_lab(
    *,
    lab_id: str,
    evidence_dir: Path,
    jira_key: str = "TG-192",
    lab_title: str | None = None,
    mgmt_sync_path: Path | None = None,
    mgmt_slot: int = 5,
    device_template: str = "iosv",
    dry_run: bool = False,
    client=None,
) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    client = client or _cml_client()
    lab = client.join_existing_lab(lab_id)
    title = lab_title or getattr(lab, "title", None) or lab_id
    mgmt_sync = load_mgmt_sync_report(mgmt_sync_path)
    mgmt_iface = mgmt_interface_name(device_template, mgmt_slot)

    alias_result = apply_ci_aliases_pyats(
        lab,
        jira_key=jira_key,
        mgmt_slot=mgmt_slot,
        device_template=device_template,
        router_ipv6=mgmt_sync.get("mapping"),
        dry_run=dry_run,
    )
    config_extract = extract_working_configs(lab, dry_run=dry_run)
    status = "pass" if alias_result.get("applied", 0) > 0 else "fail"
    report = build_ci_report(
        jira_key=jira_key,
        lab_id=lab_id,
        lab_title=title,
        status=status,
        mgmt_sync=mgmt_sync,
        config_extract={**config_extract, "ci_aliases": alias_result},
    )
    guide = build_lab_guide_html(jira_key, mgmt_sync, mgmt_iface)
    set_lab_guide(lab, guide, dry_run=dry_run)
    embed_ci_evidence(lab, report, dry_run=dry_run)
    yaml_text = download_lab_yaml(lab, dry_run=dry_run)

    report_path = evidence_dir / "ci_report.json"
    yaml_path = evidence_dir / f"{title}-post-run.yaml"
    guide_path = evidence_dir / "lab-guide.html"

    if not dry_run:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        guide_path.write_text(guide, encoding="utf-8")
        if yaml_text:
            yaml_path.write_text(yaml_text, encoding="utf-8")

    return {
        "lab_id": lab_id,
        "lab_title": title,
        "status": status,
        "ci_aliases": alias_result,
        "ci_report": str(report_path),
        "lab_yaml": str(yaml_path) if yaml_text or dry_run else None,
        "lab_guide": str(guide_path),
        "dry_run": dry_run,
    }


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="pyATS CI finalize: aliases, wr, extract, export YAML.")
    p.add_argument("--lab-id", required=True)
    p.add_argument("--evidence-dir", type=Path, required=True)
    p.add_argument("--jira-key", default="TG-192")
    p.add_argument("--lab-title")
    p.add_argument("--mgmt-sync", type=Path)
    p.add_argument("--mgmt-slot", type=int, default=5)
    p.add_argument("--device-template", default="iosv", choices=("iosv", "csr1000v"))
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    mgmt_sync = args.mgmt_sync
    if mgmt_sync is None:
        candidate = args.evidence_dir.parent / "nac" / "mgmt_sync.json"
        if candidate.is_file():
            mgmt_sync = candidate
    try:
        result = finalize_ci_lab(
            lab_id=args.lab_id,
            evidence_dir=args.evidence_dir,
            jira_key=args.jira_key,
            lab_title=args.lab_title,
            mgmt_sync_path=mgmt_sync,
            mgmt_slot=args.mgmt_slot,
            device_template=args.device_template,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
