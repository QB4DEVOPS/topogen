# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.6
# Date Modified: 2026-02-16
#
# - Called by: src/topogen/main.py
# - Reads from: Packaged templates, Config, env (VIRL2_*), models
# - Writes to: Offline YAML (--offline-yaml), CML controller via virl2_client
# - Calls into: jinja2, virl2_client, dnshost.py, lxcfrr.py, models.py
"""
TopoGen Topology Renderer - Core Topology Generation and Rendering Logic

PURPOSE:
    Core rendering engine for all topology modes. Handles both online (CML API) and
    offline (YAML file) generation. Implements the topology creation logic for:
    - Simple/NX mode: Star topology with central switch
    - Flat mode: Hierarchical unmanaged switch fabric (core + access switches)
    - Flat-pair mode: Odd-even router pairing with switch fabric
    - DMVPN mode: Hub-spoke DMVPN with NBMA underlay (flat or flat-pair)

WHO READS ME:
    - main.py: Creates Renderer instances and calls render methods

WHO I READ:
    - config.py: Config class for configuration defaults
    - models.py: TopogenNode, TopogenInterface, TopogenError, CoordsGenerator, DNShost, Point
    - dnshost.py: dnshostconfig() for DNS host configuration
    - lxcfrr.py: lxcfrr_bootconfig() for FRR LXC container configuration
    - templates/: Jinja2 templates (*.jinja2) for router configurations

DEPENDENCIES:
    External packages:
    - virl2_client: CML2 API client (ClientLibrary, Lab, Node, Interface)
    - httpx: HTTP client (ConnectTimeout, HTTPError)
    - jinja2: Template engine (Environment, PackageLoader, Template, select_autoescape)
    - networkx: Graph algorithms (for topology generation)
    - enlighten: Progress bar display

    Standard library:
    - ipaddress: IPv4 address/network calculations
    - pathlib, os: File operations
    - math: Ceiling calculations for switch counts
    - datetime: Timestamps
    - argparse: Namespace for CLI args

KEY EXPORTS:
    - Renderer: Main class containing all rendering methods
    - get_templates(): Returns list of available Jinja2 templates

KEY METHODS (Renderer class):
    Online (CML API) methods:
    - render_simple_network(): Simple/NX star topology (online)
    - render_flat_network(): Flat hierarchical topology (online)
    - render_flat_pair_network(): Flat-pair topology (online)
    - render_dmvpn(): DMVPN hub-spoke (online)

    Offline (YAML) static methods:
    - offline_simple_yaml(): Simple/NX star topology (offline YAML)
    - offline_flat_yaml(): Flat hierarchical topology (offline YAML)
    - offline_flat_pair_yaml(): Flat-pair topology (offline YAML)
    - offline_dmvpn_yaml(): DMVPN with flat underlay (offline YAML)
    - offline_dmvpn_flat_pair_yaml(): DMVPN with flat-pair underlay (offline YAML)

ARCHITECTURE:
    - Online mode: Renderer.render_*() → CML API via virl2_client
    - Offline mode: Renderer.offline_*_yaml() → YAML file generation
    - Templates: Jinja2 templates in templates/ directory render router configs
    - Addressing: Deterministic IPv4 address allocation for all interfaces
    - Layout: Deterministic X/Y coordinates for visual topology in CML

TOPOLOGY MODES:
    1. Simple/NX: Central switch + N routers (star topology)
    2. Flat: Core switch + access switches + N routers (hierarchical)
    3. Flat-pair: Odd routers paired with even routers + switch fabric
    4. DMVPN flat: Hub-spoke DMVPN with flat underlay switches
    5. DMVPN flat-pair: Hub-spoke DMVPN with flat-pair underlay

OOB MANAGEMENT:
    All modes support optional OOB management network (--mgmt):
    - SWoob0: Core OOB switch
    - SWoobN: Access OOB switches (one per group of routers)
    - ext-conn-mgmt: Optional external-connector for bridge mode (--mgmt-bridge)
"""

import html as html_module
import importlib.resources as pkg_resources
import logging
import math
import os
import threading
from pathlib import Path
from argparse import Namespace
from datetime import datetime, timezone
from ipaddress import IPV4LENGTH, IPv4Address, IPv4Interface, IPv4Network
from typing import Any, Set, Tuple, Union

import enlighten
import networkx as nx

from httpx import ConnectTimeout, HTTPError
from jinja2 import (
    Environment,
    PackageLoader,
    Template,
    TemplateNotFound,
    select_autoescape,
)
from virl2_client import ClientLibrary, InitializationError
from virl2_client.models import Interface, Lab, Node

from topogen import templates
from topogen.config import Config
from topogen.dnshost import dnshostconfig
from topogen.lxcfrr import lxcfrr_bootconfig
from topogen.models import (
    CoordsGenerator,
    DNShost,
    Point,
    TopogenError,
    TopogenInterface,
    TopogenNode,
)

_LOGGER = logging.getLogger(__name__)

EXT_CON_NAME = "ext-conn-0"
DNS_HOST_NAME = "dns-host"


# Determine package version locally to avoid circular import with topogen.__init__
try:  # Python 3.8+
    from importlib.metadata import version as _pkg_version  # type: ignore
except Exception:  # pragma: no cover - very old Python fallback
    _pkg_version = None  # type: ignore

try:
    TOPGEN_VERSION = _pkg_version("topogen") if _pkg_version else "unknown"
except Exception:  # pragma: no cover - best effort
    TOPGEN_VERSION = "unknown"


def _intent_annotation_lines(intent: str) -> list[str]:
    """Return YAML lines for annotations + smart_annotations with one hidden intent annotation.

    Embeds intent at x=-9999, y=-9999 (off-canvas) for CI/CD to grep. Same intent is also
    in lab.notes inside a hidden HTML span (visible in YAML/grep, not in CML guide).
    """
    # YAML single-quoted: escape single quote as ''
    content = intent.replace("'", "''")
    return [
        "annotations:",
        "  - border_color: '#FFFFFF'",
        "    border_style: ''",
        "    color: '#FFFFFF'",
        "    rotation: 0",
        "    text_bold: false",
        f"    text_content: '{content}'",
        "    text_font: monospace",
        "    text_italic: false",
        "    text_size: 1",
        "    text_unit: pt",
        "    thickness: 1",
        "    type: text",
        "    x1: -9999",
        "    y1: -9999",
        "    z_index: 0",
        "smart_annotations: []",
    ]


def _intent_notes_lines(intent: str) -> list[str]:
    """Return YAML lines for lab.notes: all content in white/hidden span so GUIDE shows nothing.

    Entire notes are invisible (color: white; opacity: 0). CI/CD can grep the YAML for the intent.
    """
    hidden_content = html_module.escape(intent)
    hidden_span = f'<span style="color: white; font-size: 1pt; opacity: 0;">{hidden_content}</span>'
    return [
        "  notes: |-",
        f"    {hidden_span}",
    ]


def get_templates() -> list[str]:
    """get all available templates in the package"""
    return [
        t[: -len(Renderer.J2SUFFIX)]
        for t in pkg_resources.contents(templates)
        if t.endswith(Renderer.J2SUFFIX)
    ]


def _init_client_from_args(args: Namespace) -> ClientLibrary:
    """Initialize virl2_client from CLI args (for import path; no Renderer instance)."""
    cainfo: Union[bool, str] = args.cafile
    try:
        os.stat(args.cafile)
    except (FileNotFoundError, TypeError):
        cainfo = not args.insecure
    try:
        client = ClientLibrary(ssl_verify=cainfo)
        if not client.is_system_ready():
            raise TopogenError("system is not ready")
        return client
    except ConnectTimeout as exc:
        raise TopogenError("no connection: " + str(exc)) from None
    except InitializationError as exc:
        raise TopogenError(
            "no env provided, need VIRL2_URL, VIRL2_USER and VIRL2_PASS"
        ) from exc


def _start_lab_in_background(lab: Lab, args: Namespace) -> None:
    """Start the lab in a background thread; brief delay so the start request reaches CML before process exits."""
    if not getattr(args, "start_lab", False):
        return
    _LOGGER.warning("Starting lab... (running in background; check CML UI for status)")

    def _start() -> None:
        try:
            lab.start()
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("Start failed: %s", exc)

    t = threading.Thread(target=_start, daemon=True)
    t.start()
    # Let the thread send the start request before we exit (daemon dies on process exit)
    import time
    time.sleep(3)


def disable_pcl_loggers():
    """set all virl python client library loggers to WARN, too much output"""
    loggers = [
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict  # pylint disable=E1101
    ]
    for logger in loggers:
        if logger.name.startswith("virl2_client"):
            logger.setLevel(logging.WARN)


def order_iface_pair(iface_pair: dict, this: int) -> Tuple[Any, Any]:
    """order the interface pair so that the first one is the one with the
    given index "this", and the second one is the other one.
    """
    (src_idx, src_iface), (_, dst_iface) = iface_pair.items()
    if this == src_idx:
        return src_iface, dst_iface
    return dst_iface, src_iface


def format_dns_entry(iface_pair: dict, this: int) -> str:
    """format the interface pair labels suitable for a DNS entry"""
    table = {
        ord("/"): "_",
        ord(" "): "-",
    }

    # these must be sorted by key length
    interface_names = {
        "TenGigabitEthernet": "ten",
        "GigabitEthernet": "gi",
        "Ethernet": "e",
    }

    src, dst = order_iface_pair(iface_pair, this)
    desc = f"{src.node.label}-{src.label}--{dst.node.label}-{dst.label}"

    for long, short in interface_names.items():
        if long in desc:
            desc = desc.replace(long, short)
            break

    return desc.translate(table).lower()


def format_interface_description(iface_pair: dict, this: int) -> str:
    """this puts the interface description together which gets inserted
    into the router configuration."""

    _, dst = order_iface_pair(iface_pair, this)
    # return f"from {src.node.label} {src.label} to {dst.node.label} {dst.label}"
    return f"to {dst.node.label} {dst.label}"


# Hardcoded clock set value: "today" at lab generation time (00:00:01 UTC).
# CVAC rejects EEM regexp on show clock; no parsing — single clock set so PKI can start; NTP takes over later.
def _pki_clock_set_today() -> str:
    """Return IOS clock set string: 00:00:01 Month Day Year (UTC at generation time)."""
    dt = datetime.now(timezone.utc)
    return f"00:00:01 {dt.strftime('%B %d %Y')}"


def _pki_client_clock_eem_lines() -> list[str]:
    """EEM applet CLIENT-PKI-SET-CLOCK: one-shot 90s after boot.
    If NTP synced, set TIME_DONE and exit. Else: clock set <hardcoded today>, then TIME_DONE.
    No show clock / regexp (CVAC rejects it); NTP takes over later.
    Environment variable TIME_DONE set to 0 first so run-once guard works."""
    clock_val = _pki_clock_set_today()
    lines = [
        "!",
        "event manager environment TIME_DONE 0",
        "!",
        "event manager applet CLIENT-PKI-SET-CLOCK authorization bypass",
        " event timer countdown time 90",
        " action 0.1 cli command \"enable\"",
        " action 0.2 syslog msg \"EEM CLIENT-PKI-SET-CLOCK: executed [step 0.2]\"",
        " action 0.3 cli command \"terminal length 0\"",
        " action 0.4 cli command \"show event manager environment | include TIME_DONE\"",
        " action 0.5 regexp \"TIME_DONE 1\" \"$_cli_result\" match",
        " action 0.6 if $_regexp_result eq \"1\"",
        "  action 0.7  exit",
        "  action 0.8 end",
        " action 1.0 cli command \"show ntp status\"",
        " action 1.1 regexp \"Clock is synchronized\" \"$_cli_result\" match",
        " action 1.2 if $_regexp_result eq \"1\"",
        "  action 1.3  cli command \"configure terminal\"",
        "  action 1.4  cli command \"event manager environment TIME_DONE 1\"",
        "  action 1.5  cli command \"no event manager applet CLIENT-PKI-SET-CLOCK\"",
        "  action 1.6  cli command \"end\"",
        "  action 1.7  cli command \"write memory\"",
        "  action 1.8  syslog msg \"EEM CLIENT-PKI-SET-CLOCK: TIME_DONE set (NTP synced) [step 1.8]\"",
        "  action 1.9  exit",
        "  action 1.99 end",
        "! Hardcoded clock set (no regexp) so CVAC applies; NTP takes over later.",
        " action 2.0 cli command \"configure terminal\"",
        f" action 2.1 cli command \"do clock set {clock_val}\"",
        " action 2.2 cli command \"end\"",
        " action 3.0 cli command \"configure terminal\"",
        " action 3.1 cli command \"event manager environment TIME_DONE 1\"",
        " action 3.2 cli command \"no event manager applet CLIENT-PKI-SET-CLOCK\"",
        " action 3.3 cli command \"end\"",
        " action 3.4 cli command \"write memory\"",
        " action 3.5 syslog msg \"EEM CLIENT-PKI-SET-CLOCK: TIME_DONE set (clock authoritative) [step 3.5]\"",
        "end",
        "!",
    ]
    return lines


def _pki_ca_clock_eem_lines() -> list[str]:
    """EEM applet CA-ROOT-SET-CLOCK: one-shot 90s after boot on CA-ROOT.
    If NTP synced, set TIME_DONE and exit. Else: clock set <hardcoded today>, ntp master 6, TIME_DONE.
    No show clock / regexp (CVAC rejects it); NTP takes over later.
    Environment variable TIME_DONE set to 0 first so run-once guard works."""
    clock_val = _pki_clock_set_today()
    return [
        "!",
        "event manager environment TIME_DONE 0",
        "!",
        "event manager applet CA-ROOT-SET-CLOCK authorization bypass",
        " event timer countdown time 90",
        " action 0.1 cli command \"enable\"",
        " action 0.2 syslog msg \"EEM CA-ROOT-SET-CLOCK: executed [step 0.2]\"",
        " action 0.3 cli command \"terminal length 0\"",
        " action 0.4 cli command \"show event manager environment | include TIME_DONE\"",
        " action 0.5 regexp \"TIME_DONE 1\" \"$_cli_result\" match",
        " action 0.6 if $_regexp_result eq \"1\"",
        "  action 0.7  exit",
        "  action 0.8 end",
        " action 1.0 cli command \"show ntp status\"",
        " action 1.1 regexp \"Clock is synchronized\" \"$_cli_result\" match",
        " action 1.2 if $_regexp_result eq \"1\"",
        "  action 1.3  cli command \"configure terminal\"",
        "  action 1.4  cli command \"event manager environment TIME_DONE 1\"",
        "  action 1.5  cli command \"no event manager applet CA-ROOT-SET-CLOCK\"",
        "  action 1.6  cli command \"end\"",
        "  action 1.7  cli command \"write memory\"",
        "  action 1.8  syslog msg \"EEM CA-ROOT-SET-CLOCK: TIME_DONE set (NTP synced) [step 1.8]\"",
        "  action 1.9  exit",
        " action 1.10 end",
        "! Hardcoded clock set (no regexp) so CVAC applies; then ntp master 6.",
        " action 2.0 cli command \"configure terminal\"",
        f" action 2.1 cli command \"do clock set {clock_val}\"",
        " action 2.2 cli command \"end\"",
        " action 3.0 cli command \"configure terminal\"",
        " action 3.1 cli command \"ntp master 6\"",
        " action 3.2 cli command \"end\"",
        " action 4.0 cli command \"configure terminal\"",
        " action 4.1 cli command \"event manager environment TIME_DONE 1\"",
        " action 4.2 cli command \"no event manager applet CA-ROOT-SET-CLOCK\"",
        " action 4.3 cli command \"end\"",
        " action 4.4 cli command \"write memory\"",
        " action 4.5 syslog msg \"EEM CA-ROOT-SET-CLOCK: TIME_DONE set (clock + ntp master 6) [step 4.5]\"",
        "end",
        "!",
    ]


def _pki_ca_authenticate_eem_lines() -> list[str]:
    """EEM applet CA-ROOT-AUTHENTICATE: CA-ROOT only. Triggers on syslog PKI-6-CS_ENABLED (Certificate server now enabled).
    Only the CA router sees that message; clients use a different trigger (e.g. TIME_DONE set or timer)."""
    return [
        "!",
        "event manager applet CA-ROOT-AUTHENTICATE authorization bypass",
        " event syslog pattern \"Certificate server now enabled\"",
        " action 0.1 cli command \"enable\"",
        " action 0.2 cli command \"terminal length 0\"",
        " action 0.3 cli command \"show crypto pki certificates CA-ROOT-SELF\"",
        " action 0.4 regexp \"CA Certificate\" \"$_cli_result\" match",
        " action 0.5 if $_regexp_result eq \"1\"",
        "  action 0.6  exit",
        "  action 0.7 end",
        " action 0.8 cli command \"configure terminal\"",
        " action 0.9 cli command \"crypto pki authenticate CA-ROOT-SELF\" pattern \"yes/no\"",
        " action 0.91 wait 2",
        " action 0.92 cli command \"yes\" pattern \".*\"",
        " action 0.93 cli command \" \"",
        " action 0.94 cli command \"end\"",
        " action 0.95 cli command \"write memory\"",
        " action 0.96 cli command \"configure terminal\"",
        " action 0.97 cli command \"no event manager applet CA-ROOT-AUTHENTICATE\"",
        " action 0.98 cli command \"end\"",
        " action 0.99 cli command \"write memory\"",
        "!",
        "end",
    ]


def _pki_ca_self_enroll_block_lines(hostname: str, domainname: str, ca_scep_url: str) -> list[str]:
    """Return CA self-enrollment block lines (do clock set, then ip http secure-server, trustpoint CA-ROOT-SELF).
    do clock set placed after crypto pki server CA-ROOT block and before CA-ROOT-SELF key/trustpoint (working order)."""
    fqdn = f"{hostname}.{domainname}"
    return [
        "!",
        f"do clock set {_pki_clock_set_today()}",
        "!",
        "ip http secure-server",
        "ip http secure-server trustpoint CA-ROOT-SELF",
        "!",
        "crypto key generate rsa modulus 2048 label CA-ROOT-SELF",
        "!",
        "crypto pki trustpoint CA-ROOT-SELF",
        f" enrollment url {ca_scep_url}",
        " enrollment retry count 15",
        " enrollment retry period 60",
        " auto-enroll 70 regenerate",
        f" subject-name cn={fqdn}",
        f" subject-alt-name {fqdn}",
        " revocation-check none",
        " rsakeypair CA-ROOT-SELF",
        "!",
    ]


def _inject_pki_client_trustpoint(
    rendered: str,
    hostname: str,
    domainname: str,
    ca_url: str,
    *,
    key_label: str = "CA-ROOT",
    inject_clock_eem: bool = True,
) -> str:
    """Insert PKI client trustpoint block (SCEP) before final 'end'.
    Used when --pki enabled: on non-CA routers (key_label CA-ROOT), or on CA-ROOT
    for self-enrollment (key_label CA-ROOT-SELF). FQDN in subject-name.
    When inject_clock_eem is True (default for clients), also inject EEM applet
    CLIENT-PKI-SET-CLOCK so time matches CA fallback when NTP is not synced."""
    fqdn = f"{hostname}.{domainname}"
    block = [
        "!",
        f"do clock set {_pki_clock_set_today()}",
        "!",
        "ip http secure-server",
        "ip http secure-server trustpoint CA-ROOT-SELF",
        "!",
        f"crypto key generate rsa modulus 2048 label {key_label}",
        "!",
        "crypto pki trustpoint CA-ROOT-SELF",
        f" enrollment url {ca_url}",
        " enrollment retry count 15",
        " enrollment retry period 60",
        " revocation-check none",
        f" rsakeypair {key_label}",
        f" subject-name cn={fqdn}",
        f" subject-alt-name {fqdn}",
        " auto-enroll 70 regenerate",
        "!",
        "alias configure authc crypto pki authenticate CA-ROOT-SELF",
        "!",
    ]
    if inject_clock_eem:
        block = block + _pki_client_clock_eem_lines()
    lines = rendered.splitlines()
    try:
        end_idx = next(
            i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "end"
        )
        lines[end_idx:end_idx] = block
    except StopIteration:
        lines.extend(block)
    return "\n".join(lines)


class Renderer:
    """A class to render (random) network topologies with templated configuration
    generation."""

    J2SUFFIX = ".jinja2"

    def __init__(self, args: Namespace, cfg: Config):
        self.args = args
        self.config = cfg

        self.template: Template
        self.client: ClientLibrary
        self.lab: Lab

        if args.nodes is None:
            raise TopogenError("need to provide number of nodes!")

        self.template = self.load_template()
        self.client = self.initialize_client()

        self.lab = self.client.create_lab(args.labname)
        _LOGGER.info("lab: %s", self.lab.id)

        # Populate lab description online with version and key flags (best-effort, ignore errors)
        try:
            args_bits: list[str] = [f"nodes={args.nodes}", f"-m {args.mode}", f"-T {args.template}"]
            dev_def = getattr(args, "dev_template", args.template)
            if dev_def != args.template:
                args_bits.append(f"--device-template {dev_def}")
            if getattr(args, "enable_vrf", False):
                args_bits.append("--vrf")
                if getattr(args, "pair_vrf", None):
                    args_bits.append(f"--pair-vrf {args.pair_vrf}")
            if str(args.mode).startswith("flat"):
                args_bits.append(f"--flat-group-size {args.flat_group_size}")
                if getattr(args, "loopback_255", False):
                    args_bits.append("--loopback-255")
                if getattr(args, "gi0_zero", False):
                    args_bits.append("--gi0-zero")
            if getattr(args, "enable_mgmt", False):
                args_bits.append("--mgmt")
                if getattr(args, "mgmt_vrf", None):
                    args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
                if getattr(args, "mgmt_bridge", False):
                    args_bits.append("--mgmt-bridge")
            if getattr(args, "ntp_server", None):
                args_bits.append(f"--ntp {args.ntp_server}")
                if getattr(args, "ntp_vrf", None):
                    args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
            if getattr(args, "start_lab", False):
                args_bits.append("--start")
            desc = (
                f"Generated by topogen v{TOPGEN_VERSION} (online) | args: " + " ".join(args_bits)
            )
            if getattr(args, "remark", None):
                desc += f" | remark: {args.remark}"
            if hasattr(self.lab, "description"):
                setattr(self.lab, "description", desc)  # type: ignore[attr-defined]
            elif hasattr(self.lab, "set_notes"):
                getattr(self.lab, "set_notes")(desc)  # type: ignore[misc]
        except Exception:  # pragma: no cover - best effort only
            pass

        # these will be /32 addresses
        self.loopbacks = IPv4Network(cfg.loopbacks).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.loopbacks.prefixlen
        )
        # we do not want to use .0
        next(self.loopbacks)

        # these will be /30 addresses (4 addresses, 1 network, 1 broadcast, 2
        # hosts) e.g. 2 bits (hence the -2)
        self.p2pnets = IPv4Network(cfg.p2pnets).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.p2pnets.prefixlen - 2
        )

        self.coords = iter(CoordsGenerator(distance=args.distance))

    def load_template(self) -> Template:
        """load the template"""
        name = self.args.template
        env = Environment(
            loader=PackageLoader("topogen"), autoescape=select_autoescape()
        )
        try:
            return env.get_template(f"{name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(f"template does not exist: {name}") from exc

    def _load_companion_eigrp_template_for_dmvpn_flat_pair(self) -> Template:
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        base = str(getattr(self.args, "template", ""))
        if not base.endswith("-dmvpn"):
            raise TopogenError(
                "DMVPN underlay 'flat-pair' requires a '-dmvpn' template (e.g., iosv-dmvpn or csr-dmvpn)"
            )
        eigrp_name = base[: -len("-dmvpn")] + "-eigrp"
        try:
            return env.get_template(f"{eigrp_name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(
                f"DMVPN underlay 'flat-pair' requires companion template '{eigrp_name}'"
            ) from exc

    def initialize_client(self) -> ClientLibrary:
        """initialize the PCL"""
        cainfo: Union[bool, str] = self.args.cafile
        try:
            os.stat(self.args.cafile)
        except (FileNotFoundError, TypeError):
            # TypeError is raised when cafile is None. We set
            # cafile to None when args.insecure is set.
            cainfo = not self.args.insecure

        try:
            client = ClientLibrary(ssl_verify=cainfo)
            if not client.is_system_ready():
                raise TopogenError("system is not ready")
            return client
        except ConnectTimeout as exc:
            raise TopogenError("no connection: " + str(exc)) from None
        except InitializationError as exc:
            raise TopogenError(
                "no env provided, need VIRL2_URL, VIRL2_USER and VIRL2_PASS"
            ) from exc

    @staticmethod
    def import_yaml_to_cml(yaml_path: str, args: Namespace, size_already_logged: bool = False) -> int:
        """Import an offline YAML file into CML via virl2_client.

        When size_already_logged is False (e.g. --import-yaml only), prints file size.
        When True (generate then import), offline step already printed size; skip duplicate.
        Prints lab URL and optionally starts the lab in the background (non-blocking).
        """
        disable_pcl_loggers()
        path = Path(yaml_path)
        if not path.exists():
            raise TopogenError(f"YAML file not found: {yaml_path}")
        size_bytes = path.stat().st_size
        size_kb = size_bytes / 1024
        if not size_already_logged:
            _LOGGER.warning("Lab file: %s (%.1f KB)", path, size_kb)
        _LOGGER.warning("Importing to CML...")
        client = _init_client_from_args(args)
        lab = client.import_lab_from_path(path, title=getattr(args, "labname", None) or path.stem)
        base_url = os.environ.get(
            "VIRL2_URL",
            client.url if hasattr(client, "url") else "http://localhost",
        ).rstrip("/")
        _LOGGER.warning("Lab URL: %s/lab/%s", base_url, lab.id)
        _start_lab_in_background(lab, args)
        return 0

    @staticmethod
    def validate_flat_topology(total_nodes: int, group_size: int) -> int:
        """Validate flat star L2 topology constraints and return access switch count.

        - Access switch: group_size routers + 1 uplink must be <= 32 ports
        - Core switch: number of access switches must be <= 32 ports
        """
        if group_size < 1:
            raise TopogenError("--flat-group-size must be >= 1")

        access_ports_required = group_size + 1  # routers + uplink to core
        if access_ports_required > 32:
            raise TopogenError(
                f"group size {group_size} requires {access_ports_required} ports on an access switch, "
                "which exceeds the typical 32-port limit; reduce --flat-group-size"
            )

        num_access = math.ceil(total_nodes / group_size)
        if num_access > 32:
            raise TopogenError(
                f"{total_nodes} nodes with group size {group_size} requires {num_access} access switches, "
                "which exceeds a typical 32-port core unmanaged switch; increase --flat-group-size"
            )

        return num_access

    @staticmethod
    def new_interface(cmlnode: Node) -> Interface:
        """create a new CML interface for the given node"""
        iface = cmlnode.next_available_interface()
        if iface is None:
            iface = cmlnode.create_interface()
        return iface

    def create_nx_network(self):
        """create a new random network using NetworkX"""

        # cluster size
        size = int(self.args.nodes / 8)
        size = max(size, 20)

        # how many clusters? ensure at least one
        clusters = int(self.args.nodes / size)
        remain = self.args.nodes - clusters * size
        dimensions = int(math.sqrt(self.args.nodes) * self.args.distance)

        constructor = [
            (size, size * 2, 0.999) if a < clusters else (remain, remain * 2, 0.999)
            for a in range(clusters + (1 if remain > 0 else 0))
        ]

        graph = nx.random_shell_graph(constructor)

        # for testing/troubleshooting, this is quite useful
        # graph = nx.barbell_graph(5, 0)

        if not nx.is_connected(graph):
            complement = list(nx.k_edge_augmentation(graph, k=1))
            graph.add_edges_from(complement)
        pos = nx.kamada_kawai_layout(graph, scale=dimensions)
        for key, value in pos.items():
            graph.nodes[key]["pos"] = Point(int(value[0]), int(value[1]))
        return graph

    def create_node(self, label: str, node_def: str, coords=Point(0, 0)):
        """create a CML2 node with the given attributes"""

        try:
            node = self.lab.create_node(
                label=label,
                node_definition=node_def,
                x=coords.x,
                y=coords.y,
                populate_interfaces=True,
            )
            # this is needed, otherwise the default interfaces which are created
            # might be missing locally
            self.lab.sync(topology_only=True)
            return node
        except HTTPError as exc:
            raise TopogenError("API error") from exc

    def create_ext_conn(self, coords=Point(0, 0)):
        """create an external connector node"""
        return self.create_node(EXT_CON_NAME, "external_connector", coords)

    def create_dns_host(self, coords=Point(0, 0)):
        """create the DNS host node"""
        node = self.create_node(DNS_HOST_NAME, "alpine", coords)
        node.create_interface()  # this is eth1
        return node

    def create_router(self, label: str, coords=Point(0, 0)):
        """create a router node (this uses the template given, e.g. iosv)"""
        node_def = getattr(self.args, "dev_template", self.args.template)
        return self.create_node(label, node_def, coords)

    def next_network(self) -> Set[IPv4Interface]:
        """return the next point-to-point network"""
        p2pnet = next(self.p2pnets)
        return set(IPv4Interface(f"{i}/{p2pnet.netmask}") for i in p2pnet.hosts())

    def render_node_network(self) -> int:
        """render the NX random network"""

        disable_pcl_loggers()

        manager = None
        ticks = None
        _LOGGER.warning("Creating network")
        graph = self.create_nx_network()

        if self.args.progress:
            manager = enlighten.get_manager()
            eprog = manager.counter(
                total=graph.number_of_edges() + graph.number_of_nodes(),
                desc="topology",
                unit="elements",
                leave=False,
                color="cyan",
            )

        # OOB management network setup (declare early so it's available in edge loop)
        enable_mgmt = getattr(self.args, "enable_mgmt", False)
        mgmt_slot = getattr(self.args, "mgmt_slot", 5)
        oob_switch = None
        mgmt_ext_conn = None

        # Create OOB management infrastructure BEFORE edge loop (if --mgmt enabled)
        if enable_mgmt:
            # Create OOB management switch
            oob_switch = self.create_node("SWoob0", "unmanaged_switch", Point(-200, 0))
            if hasattr(oob_switch, "hide_links"):
                oob_switch.hide_links = True
            _LOGGER.warning("OOB management switch: %s", oob_switch.label)

            # Create external connector for management bridge (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(self.args, "mgmt_bridge", False)
            if mgmt_bridge:
                mgmt_ext_conn = self.create_node("ext-conn-mgmt", "external_connector", Point(-440, 0))
                mgmt_ext_conn.configuration = "System Bridge"
                # Link external connector to OOB switch
                self.lab.create_link(
                    mgmt_ext_conn.get_interface_by_slot(0),
                    oob_switch.get_interface_by_slot(0),
                )
                _LOGGER.warning("Management external connector: %s", mgmt_ext_conn.label)
                _LOGGER.warning("Creating mgmt ext-conn link")

        _LOGGER.warning("Creating edges and nodes")
        for edge in graph.edges:
            src, dst = edge
            prefix = next(self.p2pnets)
            graph.edges[edge]["prefix"] = prefix
            graph.edges[edge]["hosts"] = iter(prefix.hosts())
            for node_index in [src, dst]:
                node = graph.nodes[node_index]
                if node.get("cml2node") is None:
                    cml2node = self.create_router(f"R{node_index + 1}", node["pos"])
                    _LOGGER.info("router: %s", cml2node.label)
                    node["cml2node"] = cml2node

                    # Connect mgmt interface immediately after router creation (before data plane)
                    if enable_mgmt and oob_switch is not None:
                        dev_def = getattr(self.args, "dev_template", self.args.template)
                        router_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                        mgmt_if = cml2node.create_interface(slot=router_mgmt_slot)
                        oob_if = self.new_interface(oob_switch)
                        self.lab.create_link(mgmt_if, oob_if)
                        _LOGGER.warning("mgmt-link: %s slot %d -> %s", cml2node.label, router_mgmt_slot, oob_switch.label)

                    if self.args.progress:
                        eprog.update()  # type:ignore
            src_iface = self.new_interface(graph.nodes[src]["cml2node"])
            dst_iface = self.new_interface(graph.nodes[dst]["cml2node"])
            self.lab.create_link(src_iface, dst_iface)

            desc = (
                f"{src_iface.node.label} {src_iface.label} -> "
                + f"{dst_iface.node.label} {dst_iface.label}"
            )
            _LOGGER.info("link: %s", desc)
            graph.edges[edge]["order"] = {
                src: src_iface,
                dst: dst_iface,
            }

            if self.args.progress:
                eprog.update()  # type: ignore

        if self.args.progress:
            nprog = manager.counter(  # type: ignore
                total=graph.number_of_nodes(),
                replace=eprog,  # type: ignore
                desc="configs ",
                unit=" configs",
                leave=False,
                color="cyan",
            )

        # create the external connector
        ext_con = self.create_ext_conn(coords=Point(0, 0))
        _LOGGER.warning("External connector: %s", ext_con.label)

        # create the DNS host
        dns_addr, dns_via = self.next_network()
        dns_host = self.create_dns_host(coords=Point(self.args.distance, 0))
        _LOGGER.warning("DNS host: %s", dns_host.label)
        dns_iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_addr.ip)
        dns_zone: list[DNShost] = []

        # link the two
        self.lab.create_link(
            ext_con.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.warning("Creating ext-conn link")

        core = sorted(
            nx.degree_centrality(graph).items(), key=lambda e: e[1], reverse=True
        )[0][0]
        _LOGGER.warning("Identified core node is R%s", core + 1)

        _LOGGER.warning("Creating node configurations")
        for node_index, nbrs in graph.adj.items():
            interfaces: list[TopogenInterface] = []

            for _, eattr in nbrs.items():
                prefix = eattr["prefix"]
                hosts = eattr["hosts"]
                order = eattr["order"]

                addr = IPv4Interface(f"{next(hosts)}/{prefix.netmask}")
                label = format_interface_description(order, node_index)
                interfaces.append(
                    TopogenInterface(address=addr, description=label, slot=order[node_index].slot)
                )
                dns_zone.append(DNShost(format_dns_entry(order, node_index), addr.ip))

            if node_index == core:
                core_iface = self.new_interface(graph.nodes[node_index]["cml2node"])
                self.lab.create_link(
                    dns_iface,
                    core_iface,
                )

                # Use a stupidly high node number for the DNS host, otherwise,
                # in case the DNS host is selected as the central node, the
                # pair would only have one element (prior to this, 0 was used
                # as the key).
                pair = {core: core_iface, 999999: dns_iface}
                label = format_interface_description(pair, node_index)
                assert core_iface.slot is not None
                interfaces.append(
                    TopogenInterface(address=dns_via, description=label, slot=core_iface.slot)
                )
                dns_zone.append(DNShost(format_dns_entry(pair, node_index), dns_via.ip))

                _LOGGER.warning("DNS host link")

            # need to sort interface list by slot
            interfaces.sort(key=lambda x: x.slot)

            # hack for IOL
            if self.args.template == "iol":
                leftover = 4 - len(interfaces) % 4
                if leftover in range(1, 4):  # 1, 2 or 3
                    for _ in range(leftover):
                        interfaces.append(
                            TopogenInterface(
                                IPv4Interface("0.0.0.0/0"),
                                description="unused",
                                slot=0,
                            )
                        )

            cmlnode: Node = graph.nodes[node_index]["cml2node"]
            loopback = IPv4Interface(next(self.loopbacks))
            node = TopogenNode(
                hostname=f"R{node_index + 1}",
                loopback=loopback,
                interfaces=interfaces,
            )

            # Build mgmt context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(self.args, "mgmt_vrf", None),
                    "gw": getattr(self.args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            # "origin" identifies the default gateway on the node connecting
            # to the DNS host
            config = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="" if node_index != core else dns_addr,
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
            )
            if cmlnode is None:
                continue
            # this is a special one-off for the LXC / frr variannt
            if self.args.template == "lxc":
                nameserver = (
                    self.config.nameserver if self.config.nameserver else dns_addr.ip
                )
                cfg = [
                    {
                        "name": "boot.sh",
                        "content": lxcfrr_bootconfig(
                            self.config,
                            node,
                            ["ospf", "bgp"],
                            str(nameserver),
                            False,
                        ),
                    },
                    {
                        "name": "node.cfg",
                        "content": config,
                    },
                ]
                cmlnode.configuration = cfg  # type: ignore[method-assign]
            else:
                cmlnode.configuration = config  # type: ignore[method-assign]

            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            _LOGGER.warning("Config created for %s", node.hostname)
            if self.args.progress:
                nprog.update()  # type: ignore

        # finalize the DNS host configuration
        node = TopogenNode(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                TopogenInterface(address=dns_addr),
                TopogenInterface(address=dns_via),
            ],
        )
        dns_zone.append(DNShost(f"{DNS_HOST_NAME}-eth1", dns_addr.ip))
        dns_host.config = dnshostconfig(self.config, node, dns_zone)
        _LOGGER.warning("Config created for DNS host")
        _LOGGER.warning("Done")

        if self.args.progress:
            nprog.close()  # type: ignore
            manager.stop()  # type: ignore

        # Print lab URL
        import os
        base_url = os.environ.get('VIRL2_URL', self.client.url if hasattr(self.client, 'url') else 'http://localhost').rstrip('/')
        _LOGGER.warning(f"Lab URL: {base_url}/lab/{self.lab.id}")

        # Start lab if requested (non-blocking)
        _start_lab_in_background(self.lab, self.args)

        return 0

    def _render_dmvpn_flat_pair_network(self, nbma_net: IPv4Network, tunnel_net: IPv4Network) -> int:
        disable_pcl_loggers()

        total_routers = int(self.args.nodes)
        total_endpoints = (total_routers + 1) // 2

        manager = None
        ticks = None

        stub_evens = bool(getattr(self.args, "eigrp_stub", False)) and str(
            getattr(self.args, "dmvpn_routing", "eigrp")
        ).lower() == "eigrp"

        dmvpn_vrf = self.args.pair_vrf if getattr(self.args, "enable_vrf", False) else None

        hubs_list = getattr(self.args, "dmvpn_hubs_list", None)
        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        max_odd_rnum = total_routers if (total_routers % 2) == 1 else (total_routers - 1)
        if max_odd_rnum > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for router number {max_odd_rnum}"
            )
        if max_odd_rnum > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for router number {max_odd_rnum}"
            )

        group = max(1, int(getattr(self.args, "flat_group_size", 20)))
        num_sw = Renderer.validate_flat_topology(total_endpoints, group)

        if self.args.progress:
            manager = enlighten.get_manager()
            ticks = manager.counter(
                total=1 + num_sw + total_routers,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        _LOGGER.warning(
            "[dmvpn/flat-pair] Creating %d routers (%d DMVPN endpoints)",
            total_routers,
            total_endpoints,
        )

        core = self.create_node("SWnbma0", "unmanaged_switch", Point(0, 0))
        if ticks:
            ticks.update()  # type: ignore
        switches: list[Node] = []
        for i in range(num_sw):
            x = (i + 1) * self.args.distance * 3
            sw = self.create_node(f"SWnbma{i+1}", "unmanaged_switch", Point(x, 0))
            switches.append(sw)
            self.lab.create_link(self.new_interface(core), self.new_interface(sw))
            if ticks:
                ticks.update()  # type: ignore

        l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"

        pair_ips: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = self.config.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())
        for odd in range(1, total_routers + 1, 2):
            even = odd + 1
            if even > total_routers:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            pair_ips[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        eigrp_template = self._load_companion_eigrp_template_for_dmvpn_flat_pair()

        routers: list[tuple[int, TopogenNode, Node]] = []
        for rnum in range(1, total_routers + 1):
            hostname = f"R{rnum}"
            sw_index = ((rnum - 1) // 2) // group
            x = (sw_index + 1) * self.args.distance * 3
            y = ((rnum - 1) % (group * 2) + 1) * self.args.distance

            cml_router = self.create_router(hostname, Point(x, y))

            hi = (rnum // 256) & 0xFF
            lo = rnum % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            if rnum % 2 == 1:
                nbma_ip = IPv4Interface(
                    f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}"
                )
                tunnel_ip = IPv4Interface(
                    f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}"
                )
                pair_ip = pair_ips.get(rnum, (None, None))[0]
                ifaces = [
                    TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                    TopogenInterface(address=pair_ip, description="pair link", slot=1),
                    TopogenInterface(address=tunnel_ip, description="dmvpn tunnel", slot=1000),
                ]
            else:
                pair_ip = pair_ips.get(rnum - 1, (None, None))[1]
                ifaces = [TopogenInterface(address=pair_ip, description="pair link", slot=0)]

            node = TopogenNode(hostname=hostname, loopback=loopback_ip, interfaces=ifaces)
            routers.append((rnum, node, cml_router))
            if ticks:
                ticks.update()  # type: ignore

        for rnum, _node, cml_router in routers:
            if (rnum % 2) == 0:
                continue
            endpoint_idx = (rnum + 1) // 2
            sw_index = (endpoint_idx - 1) // group
            sw = switches[sw_index]
            try:
                r_if = cml_router.get_interface_by_slot(0)
            except Exception:
                r_if = self.new_interface(cml_router)
            self.lab.create_link(r_if, self.new_interface(sw))

        for odd in range(1, total_routers + 1, 2):
            even = odd + 1
            if even > total_routers:
                continue
            odd_router = routers[odd - 1][2]
            even_router = routers[even - 1][2]
            try:
                odd_if = odd_router.get_interface_by_slot(1)
            except Exception:
                odd_if = self.new_interface(odd_router)
            try:
                even_if = even_router.get_interface_by_slot(0)
            except Exception:
                even_if = self.new_interface(even_router)
            self.lab.create_link(odd_if, even_if)

        hub_info: list[dict[str, IPv4Address]] = []
        for rnum, node, _cml_router in routers:
            if (rnum % 2) == 0:
                continue
            if rnum in hub_set:
                nbma_iface = next((i for i in node.interfaces if i.description == "dmvpn nbma"), None)
                tun_iface = next((i for i in node.interfaces if i.description == "dmvpn tunnel"), None)
                if nbma_iface and nbma_iface.address and tun_iface and tun_iface.address:
                    hub_info.append(
                        {
                            "hub_nbma_ip": nbma_iface.address.ip,
                            "hub_tunnel_ip": tun_iface.address.ip,
                        }
                    )

        for rnum, node, cml_router in routers:
            if (rnum % 2) == 1:
                rendered = self.template.render(
                    config=self.config,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    is_hub=(rnum in hub_set),
                    hub_info=hub_info,
                    dmvpn_tunnel_key=getattr(self.args, "dmvpn_tunnel_key", 10),
                    dmvpn_phase=getattr(self.args, "dmvpn_phase", 2),
                    dmvpn_vrf=dmvpn_vrf,
                    dmvpn_security=getattr(self.args, "dmvpn_security", "none"),
                    dmvpn_psk=getattr(self.args, "dmvpn_psk", None),
                )
                if getattr(self.args, "pki_enabled", False):
                    ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                    rendered = _inject_pki_client_trustpoint(
                        rendered, node.hostname, self.config.domainname, ca_url
                    )
            else:
                rendered = eigrp_template.render(
                    config=self.config,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    eigrp_stub=stub_evens,
                )
            try:
                cml_router.configuration = rendered  # type: ignore[method-assign]
            except Exception:
                pass

        hubs_str = ",".join(str(i["hub_tunnel_ip"]) for i in hub_info) if hub_info else ""
        _LOGGER.warning(
            "[dmvpn/flat-pair] NBMA: %s | Tunnel: %s | Hubs(tunnel): %s",
            nbma_net,
            tunnel_net,
            hubs_str,
        )

        outfile = getattr(self.args, "yaml_output", None)
        if outfile:
            try:
                content = None
                if hasattr(self.client, "export_lab"):
                    content = self.client.export_lab(self.lab.id)  # type: ignore[attr-defined]
                elif hasattr(self.lab, "export"):
                    content = self.lab.export()  # type: ignore[attr-defined]
                elif hasattr(self.lab, "topology"):
                    content = str(self.lab.topology)  # type: ignore[attr-defined]
                if content is not None:
                    data = content if isinstance(content, bytes) else str(content).encode("utf-8")
                    with open(outfile, "wb") as fh:
                        fh.write(data)
                    _LOGGER.warning("Exported lab YAML to %s", outfile)
                else:
                    _LOGGER.error("YAML export not supported by client library")
            except Exception as exc:  # pragma: no cover
                _LOGGER.error("YAML export failed: %s", exc)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    def render_dmvpn_network(self) -> int:
        """Render a DMVPN topology (hub + spokes).

        DMVPN rendering is implemented in a later step.
        """

        disable_pcl_loggers()

        manager = None
        ticks = None

        try:
            nbma_net = IPv4Network(str(getattr(self.args, "dmvpn_nbma_cidr", "10.10.0.0/16")))
            tunnel_net = IPv4Network(
                str(getattr(self.args, "dmvpn_tunnel_cidr", "172.20.0.0/16"))
            )
        except Exception as exc:
            raise TopogenError(f"Invalid DMVPN CIDR: {exc}") from None

        underlay = getattr(self.args, "dmvpn_underlay", "flat")
        if underlay == "flat-pair":
            return self._render_dmvpn_flat_pair_network(nbma_net, tunnel_net)

        hubs_list = getattr(self.args, "dmvpn_hubs_list", None)
        if hubs_list:
            total_routers = int(self.args.nodes)
            spokes = total_routers - len(hubs_list)
        else:
            spokes = int(self.args.nodes)
            total_routers = spokes + 1

        if total_routers > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for {total_routers} routers"
            )
        if total_routers > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for {total_routers} routers"
            )

        if hubs_list:
            _LOGGER.warning(
                "[dmvpn] Creating %d hubs + %d spokes (total %d routers)",
                len(hubs_list),
                spokes,
                total_routers,
            )
        else:
            _LOGGER.warning(
                "[dmvpn] Creating 1 hub + %d spokes (total %d routers)",
                spokes,
                total_routers,
            )

        if self.args.progress:
            manager = enlighten.get_manager()
            ticks = manager.counter(
                total=1 + total_routers,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        nbma_sw = self.create_node("SWnbma0", "unmanaged_switch", Point(0, 0))
        if ticks:
            ticks.update()  # type: ignore

        # Deterministic Loopback0 addressing (match flat/offline behavior)
        l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"

        routers: list[tuple[TopogenNode, Node]] = []
        for idx in range(total_routers):
            hostname = f"R{idx + 1}"
            x = (idx + 1) * self.args.distance * 2
            y = self.args.distance * 2 if idx == 0 else -self.args.distance * 2

            cml_router = self.create_router(hostname, Point(x, y))

            try:
                wan_iface = cml_router.get_interface_by_slot(0)
            except Exception:  # pragma: no cover - defensive
                wan_iface = self.new_interface(cml_router)
            self.lab.create_link(wan_iface, self.new_interface(nbma_sw))

            nbma_ip = IPv4Interface(
                f"{nbma_net.network_address + (idx + 1)}/{nbma_net.prefixlen}"
            )
            tunnel_ip = IPv4Interface(
                f"{tunnel_net.network_address + (idx + 1)}/{tunnel_net.prefixlen}"
            )

            rnum = idx + 1
            hi = (rnum // 256) & 0xFF
            lo = rnum % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")
            node = TopogenNode(
                hostname=hostname,
                loopback=loopback_ip,
                interfaces=[
                    TopogenInterface(
                        address=nbma_ip,
                        description="dmvpn nbma",
                        slot=0,
                    ),
                    TopogenInterface(
                        address=tunnel_ip,
                        description="dmvpn tunnel",
                        slot=1000,
                    ),
                ],
            )

            routers.append((node, cml_router))
            if ticks:
                ticks.update()  # type: ignore

        # hub_info is a list of {hub_nbma_ip, hub_tunnel_ip} entries used by spoke templates
        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        hub_info: list[dict[str, IPv4Address]] = []
        for idx, (node, _cml_router) in enumerate(routers):
            rnum = idx + 1
            if rnum in hub_set:
                hub_info.append(
                    {
                        "hub_nbma_ip": node.interfaces[0].address.ip,  # type: ignore[union-attr]
                        "hub_tunnel_ip": node.interfaces[1].address.ip,  # type: ignore[union-attr]
                    }
                )

        for idx, (node, cml_router) in enumerate(routers):
            rnum = idx + 1
            rendered = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                is_hub=(rnum in hub_set),
                hub_info=hub_info,
                dmvpn_tunnel_key=getattr(self.args, "dmvpn_tunnel_key", 10),
                dmvpn_phase=getattr(self.args, "dmvpn_phase", 2),
                dmvpn_security=getattr(self.args, "dmvpn_security", "none"),
                dmvpn_psk=getattr(self.args, "dmvpn_psk", None),
            )
            if getattr(self.args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, node.hostname, self.config.domainname, ca_url
                )
            try:
                cml_router.configuration = rendered  # type: ignore[method-assign]
            except Exception:
                pass

        if hub_info:
            hubs_str = ",".join(
                str(i["hub_tunnel_ip"]) for i in hub_info
            )
        else:
            hubs_str = ""
        _LOGGER.warning(
            "[dmvpn] NBMA: %s | Tunnel: %s | Hubs(tunnel): %s",
            nbma_net,
            tunnel_net,
            hubs_str,
        )

        outfile = getattr(self.args, "yaml_output", None)
        if outfile:
            try:
                content = None
                if hasattr(self.client, "export_lab"):
                    content = self.client.export_lab(self.lab.id)  # type: ignore[attr-defined]
                elif hasattr(self.lab, "export"):
                    content = self.lab.export()  # type: ignore[attr-defined]
                elif hasattr(self.lab, "topology"):
                    content = str(self.lab.topology)  # type: ignore[attr-defined]
                if content is not None:
                    if isinstance(content, bytes):
                        data = content
                    else:
                        data = str(content).encode("utf-8")
                    with open(outfile, "wb") as fh:
                        fh.write(data)
                    _LOGGER.warning("Exported lab YAML to %s", outfile)
                else:
                    _LOGGER.error("YAML export not supported by client library")
            except Exception as exc:  # pragma: no cover - best-effort export
                _LOGGER.error("YAML export failed: %s", exc)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    def render_flat_pair_network(self) -> int:
        """Render a flat L2 management network with odd-even router pairing.

        Rules:
        - Create unmanaged switches like flat mode (same guardrails and positions).
        - Odd routers: Gi0/0 -> access switch; additionally link Gi0/1 <-> even router's Gi0/0.
        - Even routers: no link to access switch; only paired to preceding odd.
        - If last odd router has no even partner, its Gi0/1 remains unused.
        - Switch port counts (guardrails) remain based on configured group size.
        - Interface IP addressing and templates remain identical to flat mode for now
          (only Gi0/0 configured); pairing link has no IP unless templates are later updated.
        """

        disable_pcl_loggers()

        total = self.args.nodes
        group = max(1, int(self.args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)

        dev_def = getattr(self.args, "dev_template", self.args.template)
        if dev_def != "iosv":
            _LOGGER.warning(
                "Using custom device template '%s'; guardrails assume ~32-port unmanaged_switch and do not account for custom node definitions/images",
                dev_def,
            )

        _LOGGER.warning(
            "[flat-pair] Creating %d unmanaged switches for %d routers (group size %d)",
            num_sw,
            total,
            group,
        )

        # Core switch
        core = self.create_node("SW0", "unmanaged_switch", Point(0, 0))

        # Access switches positioned horizontally and connected to core
        switches: list[Node] = []
        for i in range(num_sw):
            x = (i + 1) * self.args.distance * 3
            sw = self.create_node(f"SW{i+1}", "unmanaged_switch", Point(x, 0))
            switches.append(sw)
            self.lab.create_link(self.new_interface(core), self.new_interface(sw))
            _LOGGER.info("switch-link: %s <-> %s", core.label, sw.label)

        # Pre-compute /30 p2p addressing for odd-even pairs from config.p2pnets
        pair_ips: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = self.config.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())  # safe fallback, yields no addresses
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            # Assign first host to odd Gi0/1, second to even Gi0/0
            pair_ips[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        # Create routers and attach ONLY odd router Gi0/0 to the access switch
        cml_routers: list[Node] = []
        for idx in range(total):
            router_label = f"R{idx + 1}"
            sw_index = idx // group
            rx = (sw_index + 1) * self.args.distance * 3
            ry = (idx % group + 1) * self.args.distance
            cml_router = self.create_router(router_label, Point(rx, ry))
            cml_routers.append(cml_router)

            # Configure addresses as in flat mode (Loopback and Gi0/0 only)
            ridx = idx + 1
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            g_addr = IPv4Interface(f"{g_base}.{hi}.{lo}/16")
            l_addr = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            # Build per-router interface configs:
            # - Odd routers: Gi0/0 with IP, plus Gi0/1. If a pair IP exists, assign it; else L2-only.
            # - Even routers: Gi0/0. If a pair IP exists, assign it; else L2-only.
            rnum = idx + 1
            if rnum % 2 == 1:
                # odd
                odd_ip = pair_ips.get(rnum, (None, None))[0]
                pair_vrf = (
                    getattr(self.args, "pair_vrf", None)
                    if getattr(self.args, "enable_vrf", False)
                    else None
                )
                ifaces = [
                    TopogenInterface(address=g_addr, description="mgmt flat-pair", slot=0),
                    TopogenInterface(
                        address=odd_ip,
                        vrf=pair_vrf,
                        description="pair link",
                        slot=1,
                    ),
                ]
            else:
                # even
                even_ip = pair_ips.get(rnum - 1, (None, None))[1]
                ifaces = [TopogenInterface(address=even_ip, description="pair link", slot=0)]

            node = TopogenNode(
                hostname=router_label,
                loopback=l_addr,
                interfaces=ifaces,
            )
            config = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
            )
            cml_router.configuration = config  # type: ignore[method-assign]

            # Only odd routers connect Gi0/0 to access switch
            if (idx + 1) % 2 == 1:
                try:
                    r_if = cml_router.get_interface_by_slot(0)
                except Exception:
                    r_if = self.new_interface(cml_router)
                sw = switches[sw_index]
                s_if = self.new_interface(sw)
                self.lab.create_link(r_if, s_if)
                _LOGGER.info("link: %s Gi0/0 -> %s", cml_router.label, sw.label)

        # Create odd-even pairing links: R1 Gi0/1 <-> R2 Gi0/0, R3 Gi0/1 <-> R4 Gi0/0, ...
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                # No partner for last odd router; Gi0/1 remains unused
                _LOGGER.info("pair: R%d has no even partner; Gi0/1 unused", odd)
                continue

            odd_router = cml_routers[odd - 1]
            even_router = cml_routers[even - 1]

            # Ensure Gi0/1 exists on odd, Gi0/0 on even
            try:
                odd_if = odd_router.get_interface_by_slot(1)
            except Exception:
                odd_if = self.new_interface(odd_router)
            try:
                even_if = even_router.get_interface_by_slot(0)
            except Exception:
                even_if = self.new_interface(even_router)

            self.lab.create_link(odd_if, even_if)
            _LOGGER.info("pair-link: R%d Gi0/1 <-> R%d Gi0/0", odd, even)

        _LOGGER.warning("Flat-pair management network created")
        return 0

    @staticmethod
    def offline_dmvpn_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML file locally for DMVPN mode.

        This does not contact a controller. It writes a minimal topology with:
        - SWnbma0 unmanaged switch (shared NBMA underlay)
        - Routers R1..R<n+1> (R1 hub, remaining routers are spokes)
        - Links: each router's WAN interface (slot 0) connected to SWnbma0
        - Per-router configuration rendered from the selected Jinja2 template
        """

        # set up Jinja to render configs from packaged templates
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover - defensive
            raise TopogenError(f"template does not exist: {args.template}") from exc

        try:
            nbma_net = IPv4Network(str(getattr(args, "dmvpn_nbma_cidr", "10.10.0.0/16")))
            tunnel_net = IPv4Network(
                str(getattr(args, "dmvpn_tunnel_cidr", "172.20.0.0/16"))
            )
        except Exception as exc:
            raise TopogenError(f"Invalid DMVPN CIDR: {exc}") from None

        hubs_list = getattr(args, "dmvpn_hubs_list", None)
        if hubs_list:
            total_routers = int(args.nodes)
            spokes = total_routers - len(hubs_list)
        else:
            spokes = int(args.nodes)
            total_routers = spokes + 1

        manager = None
        ticks = None

        # CML input validation requires x/y coordinates to be within a bounded range.
        # The CML API currently enforces x <= 15000 (and similarly for y). Keep all
        # nodes within this range.
        max_coord = 15000

        if total_routers > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for {total_routers} routers"
            )
        if total_routers > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for {total_routers} routers"
            )

        dev_def = getattr(args, "dev_template", args.template)

        def iface_label_for_slot(slot: int) -> str:
            # CML node definitions can have different interface naming.
            # csr1000v typically uses GigabitEthernet1, GigabitEthernet2, ...
            if str(dev_def).lower() == "csr1000v":
                return f"GigabitEthernet{slot + 1}"
            return f"GigabitEthernet0/{slot}"

        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")

        args_bits: list[str] = [f"nodes={args.nodes}", f"-m {args.mode}", f"-T {args.template}"]
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        args_bits.append(f"--dmvpn-phase {getattr(args, 'dmvpn_phase', 2)}")
        args_bits.append(f"--dmvpn-routing {getattr(args, 'dmvpn_routing', 'eigrp')}")
        args_bits.append(f"--dmvpn-security {getattr(args, 'dmvpn_security', 'none')}")
        args_bits.append(f"--dmvpn-nbma-cidr {nbma_net}")
        args_bits.append(f"--dmvpn-tunnel-cidr {tunnel_net}")
        if hubs_list:
            args_bits.append(f"--dmvpn-hubs {getattr(args, 'dmvpn_hubs')}")
        if getattr(args, "pki_enabled", False):
            args_bits.append("--pki")
        version = getattr(args, "cml_version", "0.3.0")
        if version:
            args_bits.append(f"--cml-version {version}")
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")

        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, dmvpn) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f"  description: \"{desc}\"")
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        lines.append("nodes:")

        node_ids: dict[str, str] = {}
        nid = 0

        # NBMA underlay: flat-style star fabric (like flat mode)
        # One core unmanaged switch (SWnbma0) plus N access switches (SWnbma1..N).
        # Each router's WAN interface connects to exactly one access switch; each access
        # switch has one uplink to the core. This avoids the unmanaged_switch 32-port cap.
        MAX_SW_PORTS = 32
        group = max(1, int(getattr(args, "flat_group_size", 20)))
        if group + 1 > MAX_SW_PORTS:
            raise TopogenError(
                f"Invalid --flat-group-size {group}: requires {group + 1} ports per access switch (>32). Reduce --flat-group-size."
            )

        from math import ceil

        num_access = ceil(total_routers / group)
        if num_access > MAX_SW_PORTS:
            raise TopogenError(
                f"DMVPN NBMA requires {num_access} access switches with group_size={group}, but core unmanaged_switch supports only 32 uplinks. Increase --flat-group-size."
            )

        # OOB management switches (if --mgmt enabled) - mirrors NBMA switch pattern
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            num_oob_sw = num_access  # Match the number of NBMA switches
            # Precompute how many routers per OOB access switch (same grouping as NBMA)
            for i in range(num_oob_sw):
                start = i * oob_group
                end = min((i + 1) * oob_group, total_routers)
                oob_per_sw_counts.append(max(0, end - start))

        if getattr(args, "progress", False):
            manager = enlighten.get_manager()
            oob_ticks = (1 + (2 * num_oob_sw) + total_routers) if enable_mgmt else 0
            ticks = manager.counter(
                total=1 + (2 * num_access) + (2 * total_routers) + oob_ticks,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        # Match flat/flat-pair layout: core at (0,0), access switches along +X,
        # routers stacked under their access switch.
        base_distance = int(getattr(args, "distance", 200))
        base_sw_step_x = base_distance * 3
        # Scale X spacing so the right-most access switch stays within max_coord.
        sw_step_x = max(1, min(base_sw_step_x, max_coord // max(1, (num_access + 1))))
        # Scale router Y spacing so the bottom-most router stays within max_coord.
        router_step_y = max(1, min(base_distance, max_coord // max(1, (group + 2))))

        # Core NBMA switch (one port per access switch + one for CA-ROOT if --pki)
        swnbma0_port_count = num_access
        if getattr(args, "pki_enabled", False):
            swnbma0_port_count += 1
        node_ids["SWnbma0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SWnbma0']}")
        lines.append("    label: SWnbma0")
        lines.append("    node_definition: unmanaged_switch")
        lines.append("    x: 0")
        lines.append("    y: 0")
        lines.append("    interfaces:")
        for p in range(swnbma0_port_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append("        type: physical")

        if ticks:
            ticks.update()  # type: ignore

        # Access NBMA switches (each has 1 uplink + router-facing ports)
        # router_port_map[idx] -> (access_switch_label, access_port)
        router_port_map: list[tuple[str, int]] = []
        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            node_ids[sw_label] = f"n{nid}"; nid += 1
            sx = min(max_coord, (sidx + 1) * sw_step_x)
            lines.append(f"  - id: {node_ids[sw_label]}")
            lines.append(f"    label: {sw_label}")
            lines.append("    node_definition: unmanaged_switch")
            lines.append(f"    x: {sx}")
            lines.append("    y: 0")
            lines.append("    interfaces:")

            start = sidx * group
            end = min((sidx + 1) * group, total_routers)
            router_count = max(0, end - start)
            if_count = 1 + router_count
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append("        type: physical")

            for p in range(1, if_count):
                router_port_map.append((sw_label, p))

            if ticks:
                ticks.update()  # type: ignore

        # OOB management switches (if --mgmt enabled)
        if enable_mgmt:
            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            for p in range(num_oob_sw):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append("        type: physical")

            if ticks:
                ticks.update()  # type: ignore

            # OOB access switches
            base_distance = int(getattr(args, "distance", 200))
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * base_distance
                oy = (i + 1) * base_distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {oy}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append("        type: physical")

                if ticks:
                    ticks.update()  # type: ignore

        # Determine hub set and precompute hub_info for spoke templates
        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        hub_info: list[dict[str, IPv4Address]] = []
        for rnum in range(1, total_routers + 1):
            if rnum not in hub_set:
                continue
            hub_info.append(
                {
                    "hub_nbma_ip": IPv4Interface(
                        f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}"
                    ).ip,
                    "hub_tunnel_ip": IPv4Interface(
                        f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}"
                    ).ip,
                }
            )

        # Deterministic Loopback0 addressing (match flat mode)
        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"

        # Routers
        for idx in range(total_routers):
            n = idx + 1
            label = f"R{n}"
            node_ids[label] = f"n{nid}"; nid += 1

            nbma_ip = IPv4Interface(
                f"{nbma_net.network_address + n}/{nbma_net.prefixlen}"
            )
            tunnel_ip = IPv4Interface(
                f"{tunnel_net.network_address + n}/{tunnel_net.prefixlen}"
            )

            hi = (n // 256) & 0xFF
            lo = n % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")
            node = TopogenNode(
                hostname=label,
                loopback=loopback_ip,
                interfaces=[
                    TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                    TopogenInterface(address=tunnel_ip, description="dmvpn tunnel", slot=1000),
                ],
            )

            # Build mgmt context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            rendered = tpl.render(
                config=cfg,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                is_hub=(n in hub_set),
                hub_info=hub_info,
                dmvpn_tunnel_key=getattr(args, "dmvpn_tunnel_key", 10),
                dmvpn_phase=getattr(args, "dmvpn_phase", 2),
                dmvpn_security=getattr(args, "dmvpn_security", "none"),
                dmvpn_psk=getattr(args, "dmvpn_psk", None),
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
            )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )

            # Flat-like placement
            sw_index = idx // group
            x = min(max_coord, (sw_index + 1) * sw_step_x)
            y = min(max_coord, (idx % group + 1) * router_step_y)
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {x}")
            lines.append(f"    y: {y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append(f"        label: {iface_label_for_slot(0)}")
            lines.append("        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in rendered.splitlines():
                lines.append(f"      {ln}")

            if ticks:
                ticks.update()  # type: ignore

        # CA-ROOT node (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1
            ca_nbma_ip = IPv4Interface(f"{nbma_net.broadcast_address - 1}/{nbma_net.prefixlen}")
            ca_loopback_ip = IPv4Interface(f"{l_base}.255.254/32")
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=ca_loopback_ip,
                interfaces=[
                    TopogenInterface(
                        address=ca_nbma_ip,
                        description="=== SCEP Enrollment URL ===",
                        slot=0,
                    )
                ],
            )
            try:
                ca_base_tpl = env.get_template(f"csr-eigrp{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                raise TopogenError("CA template not found: csr-eigrp")
            ca_mgmt_ctx = None
            if enable_mgmt:
                ca_mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
            )
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "ip http secure-server",
                "ip http secure-server trustpoint CA-ROOT-SELF",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]
            ca_config_lines = ca_base_config.splitlines()
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"
            ca_scep_url = f"http://{ca_nbma_ip.ip}:80"
            insert_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + _pki_ca_authenticate_eem_lines()
            )
            try:
                end_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip() == "end")
                ca_config_lines[end_idx:end_idx] = insert_block
            except StopIteration:
                ca_config_lines.extend(insert_block)
            ca_rendered = "\n".join(ca_config_lines)
            ca_x = -400
            ca_y = 200
            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append("    node_definition: csr1000v")
            lines.append(f"    x: {ca_x}")
            lines.append(f"    y: {ca_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                ca_mgmt_slot_id = mgmt_slot - 1
                lines.append(f"      - id: i{ca_mgmt_slot_id}")
                lines.append(f"        slot: {ca_mgmt_slot_id}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in ca_rendered.splitlines():
                lines.append(f"      {ln}")

        # Links
        lines.append("links:")
        lid = 0

        # Access-to-core links (NBMA fabric uplinks)
        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[sw_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{sidx}")

            if ticks:
                ticks.update()  # type: ignore

        # CA-ROOT -> SWnbma0 data link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            swnbma0_ca_port = num_access
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{swnbma0_ca_port}")

        # Router-to-NBMA links (each router uses its slot-0 interface)
        for idx in range(total_routers):
            rlabel = f"R{idx + 1}"
            sw_label, sw_port = router_port_map[idx]
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[sw_label]}")
            lines.append(f"    i2: i{sw_port}")

            if ticks:
                ticks.update()  # type: ignore

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

                if ticks:
                    ticks.update()  # type: ignore

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for idx in range(total_routers):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

                if ticks:
                    ticks.update()  # type: ignore

        outfile = Path(getattr(args, "offline_yaml"))
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _intent_annotation_lines(desc) + lines
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (dmvpn) written to %s (%.1f KB)", outfile, size_kb)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    @staticmethod
    def offline_dmvpn_flat_pair_yaml(args: Namespace, cfg: Config) -> int:
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            dmvpn_tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover
            raise TopogenError(f"template does not exist: {args.template}") from exc

        stub_evens = bool(getattr(args, "eigrp_stub", False)) and str(
            getattr(args, "dmvpn_routing", "eigrp")
        ).lower() == "eigrp"

        dmvpn_vrf = args.pair_vrf if getattr(args, "enable_vrf", False) else None

        base = str(getattr(args, "template", ""))
        if not base.endswith("-dmvpn"):
            raise TopogenError(
                "DMVPN underlay 'flat-pair' requires a '-dmvpn' template (e.g., iosv-dmvpn or csr-dmvpn)"
            )
        eigrp_name = base[: -len("-dmvpn")] + "-eigrp"
        try:
            eigrp_tpl = env.get_template(f"{eigrp_name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(
                f"DMVPN underlay 'flat-pair' requires companion template '{eigrp_name}'"
            ) from exc

        try:
            nbma_net = IPv4Network(str(getattr(args, "dmvpn_nbma_cidr", "10.10.0.0/16")))
            tunnel_net = IPv4Network(str(getattr(args, "dmvpn_tunnel_cidr", "172.20.0.0/16")))
        except Exception as exc:
            raise TopogenError(f"Invalid DMVPN CIDR: {exc}") from None

        hubs_list = getattr(args, "dmvpn_hubs_list", None)
        total_routers = int(args.nodes)
        total_endpoints = (total_routers + 1) // 2

        manager = None
        ticks = None

        max_odd_rnum = total_routers if (total_routers % 2) == 1 else (total_routers - 1)
        if max_odd_rnum > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for router number {max_odd_rnum}"
            )
        if max_odd_rnum > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for router number {max_odd_rnum}"
            )

        max_coord = 15000
        group = max(1, int(getattr(args, "flat_group_size", 20)))
        num_access = Renderer.validate_flat_topology(total_endpoints, group)
        base_distance = int(getattr(args, "distance", 200))
        base_sw_step_x = base_distance * 3
        sw_step_x = max(1, min(base_sw_step_x, max_coord // max(1, (num_access + 1))))
        router_step_y = max(1, min(base_distance, max_coord // max(1, (group * 2 + 2))))

        # OOB management switches (if --mgmt enabled)
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            num_oob_sw = num_access  # Match the number of NBMA switches
            # Precompute how many routers per OOB access switch
            # In flat-pair, routers are paired (total_endpoints is the pair count)
            # But we connect ALL routers to mgmt, so use total_routers
            from math import ceil
            routers_per_oob = ceil(total_routers / num_oob_sw)
            for i in range(num_oob_sw):
                start = i * routers_per_oob
                end = min((i + 1) * routers_per_oob, total_routers)
                oob_per_sw_counts.append(max(0, end - start))

        if getattr(args, "progress", False):
            manager = enlighten.get_manager()
            oob_ticks = (1 + (2 * num_oob_sw) + total_routers) if enable_mgmt else 0
            ticks = manager.counter(
                total=1 + (2 * num_access) + total_routers + (2 * total_endpoints) + oob_ticks,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        dev_def = getattr(args, "dev_template", args.template)

        def iface_label_for_slot(slot: int) -> str:
            if str(dev_def).lower() == "csr1000v":
                return f"GigabitEthernet{slot + 1}"
            return f"GigabitEthernet0/{slot}"

        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")

        args_bits: list[str] = [f"nodes={args.nodes}", f"-m {args.mode}", f"-T {args.template}"]
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        args_bits.append(f"--dmvpn-underlay {getattr(args, 'dmvpn_underlay', 'flat')}")
        args_bits.append(f"--dmvpn-phase {getattr(args, 'dmvpn_phase', 2)}")
        args_bits.append(f"--dmvpn-routing {getattr(args, 'dmvpn_routing', 'eigrp')}")
        if stub_evens:
            args_bits.append("--eigrp-stub")
        args_bits.append(f"--dmvpn-security {getattr(args, 'dmvpn_security', 'none')}")
        args_bits.append(f"--dmvpn-nbma-cidr {nbma_net}")
        args_bits.append(f"--dmvpn-tunnel-cidr {tunnel_net}")
        if hubs_list:
            args_bits.append(f"--dmvpn-hubs {getattr(args, 'dmvpn_hubs')}")
        if getattr(args, "pki_enabled", False):
            args_bits.append("--pki")
        version = getattr(args, "cml_version", "0.3.0")
        if version:
            args_bits.append(f"--cml-version {version}")
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, dmvpn flat-pair) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f"  description: \"{desc}\"")
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        lines.append("nodes:")

        node_ids: dict[str, str] = {}
        nid = 0

        node_ids["SWnbma0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SWnbma0']}")
        lines.append("    label: SWnbma0")
        lines.append("    node_definition: unmanaged_switch")
        lines.append("    x: 0")
        lines.append("    y: 0")
        # Core interfaces: one per access switch + 1 extra for CA-ROOT if --pki enabled
        swnbma0_port_count = num_access
        if getattr(args, "pki_enabled", False):
            swnbma0_port_count += 1
        lines.append("    interfaces:")
        for p in range(swnbma0_port_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append("        type: physical")

        endpoint_port_map: list[tuple[str, int]] = []
        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            node_ids[sw_label] = f"n{nid}"; nid += 1
            sx = min(max_coord, (sidx + 1) * sw_step_x)
            lines.append(f"  - id: {node_ids[sw_label]}")
            lines.append(f"    label: {sw_label}")
            lines.append("    node_definition: unmanaged_switch")
            lines.append(f"    x: {sx}")
            lines.append("    y: 0")
            lines.append("    interfaces:")

            start = sidx * group
            end = min((sidx + 1) * group, total_endpoints)
            ep_count = max(0, end - start)
            if_count = 1 + ep_count
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append("        type: physical")
            for p in range(1, if_count):
                endpoint_port_map.append((sw_label, p))

            if ticks:
                ticks.update()  # type: ignore

        # OOB management switches (if --mgmt enabled)
        if enable_mgmt:
            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            # Ports for OOB access switches + 1 extra for CA-ROOT if --pki enabled
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append("        type: physical")

            if ticks:
                ticks.update()  # type: ignore

            # OOB access switches
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * base_distance
                oy = (i + 1) * base_distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {oy}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append("        type: physical")

                if ticks:
                    ticks.update()  # type: ignore

        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        hub_info: list[dict[str, IPv4Address]] = []
        for ep in range(1, total_endpoints + 1):
            rnum = ep * 2 - 1
            if rnum not in hub_set:
                continue
            hub_info.append(
                {
                    "hub_nbma_ip": IPv4Interface(
                        f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}"
                    ).ip,
                    "hub_tunnel_ip": IPv4Interface(
                        f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}"
                    ).ip,
                }
            )

        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"

        pair_ips: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = cfg.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())
        for odd in range(1, total_routers + 1, 2):
            even = odd + 1
            if even > total_routers:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            pair_ips[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        for idx in range(total_routers):
            rnum = idx + 1
            label = f"R{rnum}"
            node_ids[label] = f"n{nid}"; nid += 1

            hi = (rnum // 256) & 0xFF
            lo = rnum % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            # Build mgmt context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            if rnum % 2 == 1:
                nbma_ip = IPv4Interface(f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}")
                tun_ip = IPv4Interface(f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}")
                pair_ip = pair_ips.get(rnum, (None, None))[0]
                node = TopogenNode(
                    hostname=label,
                    loopback=loopback_ip,
                    interfaces=[
                        TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                        TopogenInterface(address=pair_ip, description="pair link", slot=1),
                        TopogenInterface(address=tun_ip, description="dmvpn tunnel", slot=1000),
                    ],
                )
                rendered = dmvpn_tpl.render(
                    config=cfg,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    is_hub=(rnum in hub_set),
                    hub_info=hub_info,
                    dmvpn_tunnel_key=getattr(args, "dmvpn_tunnel_key", 10),
                    dmvpn_phase=getattr(args, "dmvpn_phase", 2),
                    dmvpn_vrf=dmvpn_vrf,
                    dmvpn_security=getattr(args, "dmvpn_security", "none"),
                    dmvpn_psk=getattr(args, "dmvpn_psk", None),
                    mgmt=mgmt_ctx,
                    ntp=ntp_ctx,
                    ntp_oob=ntp_oob_ctx,
                )
            else:
                pair_ip = pair_ips.get(rnum - 1, (None, None))[1]
                node = TopogenNode(
                    hostname=label,
                    loopback=loopback_ip,
                    interfaces=[TopogenInterface(address=pair_ip, description="pair link", slot=0)],
                )
                rendered = eigrp_tpl.render(
                    config=cfg,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    eigrp_stub=stub_evens,
                    mgmt=mgmt_ctx,
                    ntp=ntp_ctx,
                    ntp_oob=ntp_oob_ctx,
                )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )

            sw_index = ((rnum - 1) // 2) // group
            x = min(max_coord, (sw_index + 1) * sw_step_x)
            y = min(max_coord, ((rnum - 1) % (group * 2) + 1) * router_step_y)

            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {x}")
            lines.append(f"    y: {y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append(f"        label: {iface_label_for_slot(0)}")
            lines.append("        type: physical")
            if rnum % 2 == 1:
                lines.append("      - id: i1")
                lines.append("        slot: 1")
                lines.append(f"        label: {iface_label_for_slot(1)}")
                lines.append("        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in rendered.splitlines():
                lines.append(f"      {ln}")

        # CA-ROOT node (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1

            # CA gets last usable IP in NBMA CIDR (avoid conflict with sequential router allocation)
            ca_nbma_ip = IPv4Interface(f"{nbma_net.broadcast_address - 1}/{nbma_net.prefixlen}")

            # CA loopback at upper end (same as flat mode: .255.254) for consistency with future CAs
            ca_loopback_ip = IPv4Interface(f"{l_base}.255.254/32")

            # Create CA node with NBMA interface (connects to SWnbma0)
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=ca_loopback_ip,
                interfaces=[
                    TopogenInterface(
                        address=ca_nbma_ip,
                        description="=== SCEP Enrollment URL ===",
                        slot=0,
                    )
                ],
            )

            # CA always uses EIGRP template (DMVPN default routing protocol)
            try:
                ca_base_tpl = env.get_template(f"csr-eigrp{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                raise TopogenError("CA template not found: csr-eigrp")

            # Render base config with EIGRP routing
            ca_mgmt_ctx = None
            if enable_mgmt:
                ca_mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
            )

            # Append PKI-specific config
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "ip http secure-server",
                "ip http secure-server trustpoint CA-ROOT-SELF",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]

            ca_config_lines = ca_base_config.splitlines()

            # Replace generic RSA key with named key (needed for PKI server)
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"

            # PKI block before EEM so double end/end does not quit config too soon
            ca_scep_url = f"http://{ca_nbma_ip.ip}:80"
            insert_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + _pki_ca_authenticate_eem_lines()
            )
            try:
                end_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip() == "end")
                ca_config_lines[end_idx:end_idx] = insert_block
            except StopIteration:
                ca_config_lines.extend(insert_block)

            ca_rendered = "\n".join(ca_config_lines)

            # Place CA near SWnbma0 (core switch area)
            ca_x = -400
            ca_y = 200

            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append("    node_definition: csr1000v")  # CA is always CSR
            lines.append(f"    x: {ca_x}")
            lines.append(f"    y: {ca_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                ca_mgmt_slot_id = mgmt_slot - 1  # CA is always CSR, so slot-1
                lines.append(f"      - id: i{ca_mgmt_slot_id}")
                lines.append(f"        slot: {ca_mgmt_slot_id}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in ca_rendered.splitlines():
                lines.append(f"      {ln}")

        lines.append("links:")
        lid = 0

        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[sw_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{sidx}")

        # CA-ROOT -> SWnbma0 data link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # SWnbma0's next available port after access switches
            swnbma0_ca_port = num_access
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{swnbma0_ca_port}")

        for ep in range(1, total_endpoints + 1):
            rlabel = f"R{ep * 2 - 1}"
            sw_label, sw_port = endpoint_port_map[ep - 1]
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[sw_label]}")
            lines.append(f"    i2: i{sw_port}")

            if ticks:
                ticks.update()  # type: ignore

        for ep in range(1, total_endpoints + 1):
            odd = ep * 2 - 1
            even = odd + 1
            if even > total_routers:
                continue
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[f'R{odd}']}")
            lines.append("    i1: i1")
            lines.append(f"    n2: {node_ids[f'R{even}']}")
            lines.append("    i2: i0")

            if ticks:
                ticks.update()  # type: ignore

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

                if ticks:
                    ticks.update()  # type: ignore

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            # Map each router to an OOB access switch
            routers_per_oob = (total_routers + num_oob_sw - 1) // num_oob_sw
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for rnum in range(1, total_routers + 1):
                rlabel = f"R{rnum}"
                oob_sw_index = (rnum - 1) // routers_per_oob
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

                if ticks:
                    ticks.update()  # type: ignore

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                # CA is always CSR1000v, so use slot - 1
                ca_mgmt_iface_id = mgmt_slot - 1
                # SWoob0's next available port after ext-conn-mgmt (if present) and OOB access switches
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

        outfile = Path(getattr(args, "offline_yaml"))
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _intent_annotation_lines(desc) + lines
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (dmvpn, flat-pair) written to %s (%.1f KB)", outfile, size_kb)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    @staticmethod
    def offline_flat_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML file locally for flat mode.

        This does not contact a controller. It writes a minimal topology with:
        - SW0 core unmanaged switch
        - SW1..N access unmanaged switches (N = ceil(nodes/group))
        - Routers R1..R<n> using args.dev_template (e.g., iosv)
        - Links: each access switch linked to SW0; each router Gi0/0 to its access switch
        - Per-router configuration rendered from the selected Jinja2 template
        """

        # set up Jinja to render configs from packaged templates
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover - defensive
            raise TopogenError(f"template does not exist: {args.template}") from exc

        total = int(args.nodes)
        group = max(1, int(args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)

        # Warn about custom device templates/images which may affect interface behavior
        dev_def = getattr(args, "dev_template", args.template)
        if dev_def != "iosv":
            _LOGGER.warning(
                "Using custom device template '%s'; guardrails assume ~32-port unmanaged_switch and do not account for custom node definitions/images",
                dev_def,
            )

        # helper to compute addressing
        def addr_parts(n: int) -> tuple[int, int]:
            ridx = n
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            return hi, lo

        # Build YAML using CML 2.5+ schema (ids for nodes/links, and n1/i1/n2/i2)
        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")
        # Build an args summary to embed into the lab description (no secrets)
        args_bits: list[str] = [f"nodes={total}", f"-m {args.mode}", f"-T {args.template}"]
        dev_def = getattr(args, "dev_template", args.template)
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        if getattr(args, "enable_vrf", False):
            args_bits.append("--vrf")
            if getattr(args, "pair_vrf", None):
                args_bits.append(f"--pair-vrf {args.pair_vrf}")
        if args.mode.startswith("flat"):
            args_bits.append(f"--flat-group-size {args.flat_group_size}")
            if getattr(args, "loopback_255", False):
                args_bits.append("--loopback-255")
            if getattr(args, "gi0_zero", False):
                args_bits.append("--gi0-zero")
        version = getattr(args, "cml_version", "0.3.0")
        if version:
            args_bits.append(f"--cml-version {version}")
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f'  description: "{desc}"')
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        lines.append("nodes:")

        node_ids: dict[str, str] = {}
        nid = 0
        # Core switch
        node_ids["SW0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SW0']}")
        lines.append("    label: SW0")
        lines.append("    node_definition: unmanaged_switch")
        lines.append("    x: 0")
        lines.append("    y: 0")

        # Access switches with interface inventory
        # Precompute how many routers per access switch
        per_sw_counts: list[int] = []
        for i in range(num_sw):
            start = i * group + 1
            end = min((i + 1) * group, total)
            per_sw_counts.append(max(0, end - start + 1))

        # Core switch needs one port per access switch + 1 for CA if --pki
        core_if_count = num_sw
        if getattr(args, "pki_enabled", False):
            core_if_count += 1
        lines.append("    interfaces:")
        for p in range(core_if_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append(f"        type: physical")

        # Access switches
        access_if_start_slots: list[int] = []
        for i in range(num_sw):
            label = f"SW{i+1}"
            node_ids[label] = f"n{nid}"; nid += 1
            x = (i + 1) * args.distance * 3
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append("    node_definition: unmanaged_switch")
            lines.append(f"    x: {x}")
            lines.append("    y: 0")
            # Each access switch: 1 uplink + ports for attached routers
            if_count = 1 + per_sw_counts[i]
            lines.append("    interfaces:")
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append(f"        type: physical")
            access_if_start_slots.append(0)

        # OOB management switches (if --mgmt enabled) - mirrors access switch pattern
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            from math import ceil
            num_oob_sw = ceil(total / oob_group)
            # Precompute how many routers per OOB access switch
            for i in range(num_oob_sw):
                start = i * oob_group + 1
                end = min((i + 1) * oob_group, total)
                oob_per_sw_counts.append(max(0, end - start + 1))

            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            # Ports for OOB access switches + 1 extra for CA-ROOT if --pki enabled
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append(f"        type: physical")

            # OOB access switches
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * args.distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {(i + 1) * args.distance}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append(f"        type: physical")

        # Routers (with Gi0/0 interface defined at slot 0)
        dev_def = getattr(args, "dev_template", args.template)
        g_base = "10.0" if getattr(args, "gi0_zero", False) else "10.10"
        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"
        for idx in range(total):
            n = idx + 1
            label = f"R{n}"
            node_ids[label] = f"n{nid}"; nid += 1
            hi, lo = addr_parts(n)
            g_ip = f"{g_base}.{hi}.{lo}"
            l_ip = f"{l_base}.{hi}.{lo}"

            # Render configuration using the same template logic as online path
            node = TopogenNode(
                hostname=label,
                loopback=IPv4Interface(f"{l_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{g_ip}/16"), description="mgmt flat", slot=0
                    )
                ],
            )
            # Build mgmt context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            rendered = tpl.render(
                config=cfg,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
            )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )

            rx = (idx // group + 1) * args.distance * 3
            ry = (idx % group + 1) * args.distance
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {rx}")
            lines.append(f"    y: {ry}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            if dev_def == "csr1000v":
                lines.append("        label: GigabitEthernet1")
            else:
                lines.append("        label: GigabitEthernet0/0")
            lines.append("        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in rendered.splitlines():
                lines.append(f"      {ln}")

        # Create PKI Root CA router if --pki enabled
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1

            # CA gets last usable IP in the flat CIDR (e.g., 10.10.255.254/16)
            ca_g_ip = f"{g_base}.255.254"
            ca_l_ip = f"{l_base}.255.254"

            # CA-ROOT is always CSR1000v (required for PKI server features)
            ca_dev_def = "csr1000v"

            # Determine which CSR template to use based on regular router template
            # This ensures CA uses same routing protocol as regular routers
            template_name = getattr(args, "template", "iosv")
            if "ospf" in template_name or template_name == "iosv":  # iosv defaults to OSPF
                ca_template_name = "csr-ospf"
            elif "eigrp" in template_name:
                ca_template_name = "csr-eigrp"
            else:
                ca_template_name = "csr-eigrp"  # Default to EIGRP if unknown

            # Load appropriate CSR template
            try:
                ca_base_tpl = env.get_template(f"{ca_template_name}{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                ca_base_tpl = tpl  # Fallback to default template

            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=IPv4Interface(f"{ca_l_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{ca_g_ip}/16"), description="=== SCEP Enrollment URL ===", slot=0
                    )
                ],
            )
            ca_mgmt_ctx = None
            if enable_mgmt:
                ca_mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            # Render base config with routing protocol
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
            )

            # CA clock EEM: one-shot 90s to set clock + ntp master if NTP not synced (so PKI server can start)
            ca_config_lines = ca_base_config.rstrip().split('\n')
            # Remove trailing "end" if present
            if ca_config_lines and ca_config_lines[-1].strip() == "end":
                ca_config_lines.pop()

            # Replace generic RSA key with named key for PKI
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"
                    break

            # PKI block before EEM so double end/end does not quit config too soon
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "ip http secure-server",
                "ip http secure-server trustpoint CA-ROOT-SELF",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]
            ca_scep_url = f"http://{ca_g_ip}:80"
            ca_config_lines.extend(pki_config_lines)
            ca_config_lines.extend(_pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url))
            ca_config_lines.extend(_pki_ca_authenticate_eem_lines())
            ca_config_lines.append("end")

            ca_rendered = '\n'.join(ca_config_lines)

            # Position CA to the left of SW0
            ca_x = -args.distance * 3
            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append(f"    node_definition: {ca_dev_def}")
            lines.append(f"    x: {ca_x}")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            if ca_dev_def == "csr1000v":
                lines.append("        label: GigabitEthernet1")
            else:
                lines.append("        label: GigabitEthernet0/0")
            lines.append("        type: physical")
            if enable_mgmt:
                if ca_dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in ca_rendered.splitlines():
                lines.append(f"      {ln}")

        # Links section
        lines.append("links:")
        lid = 0
        # Access -> core (use port equal to index for both ends)
        for i in range(num_sw):
            acc = f"SW{i+1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[acc]}")
            lines.append(f"    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{i}")
        # Routers -> access switch
        per_sw_next_port = [1 for _ in range(num_sw)]  # reserve 0 for uplink
        for idx in range(total):
            n = idx + 1
            rlabel = f"R{n}"
            sw_index = idx // group + 1
            acc = f"SW{sw_index}"
            acc_port = per_sw_next_port[sw_index - 1]
            per_sw_next_port[sw_index - 1] += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[acc]}")
            lines.append(f"    i2: i{acc_port}")

        # CA-ROOT -> SW0 link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # SW0's next available port is after all access switch uplinks (i0 through i{num_sw-1})
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{num_sw}")

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for idx in range(total):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                # CA is always CSR1000v, so use slot - 1
                ca_mgmt_iface_id = mgmt_slot - 1
                # SWoob0's next available port after ext-conn-mgmt (if present) and OOB access switches
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

        outfile = Path(getattr(args, "offline_yaml"))
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _intent_annotation_lines(desc) + lines
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (flat) written to %s (%.1f KB)", outfile, size_kb)
        return 0
    @staticmethod
    def offline_flat_pair_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML locally for flat-pair mode.

        Differences from flat:
        - Only odd routers connect Gi0/0 to the access switch.
        - Each odd router also links Gi0/1 <-> even router's Gi0/0.
        - If last odd has no partner, its Gi0/1 remains unused.
        - Access/core switches and guardrails are identical to flat; port counts unchanged.
        - Interfaces receive same addressing as flat for Gi0/0 (deterministic), pair link has no IPs.
        """

        # set up Jinja to render configs from packaged templates
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover - defensive
            raise TopogenError(f"template does not exist: {args.template}") from exc

        total = int(args.nodes)
        group = max(1, int(args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)

        # helper to compute addressing
        def addr_parts(n: int) -> tuple[int, int]:
            ridx = n
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            return hi, lo

        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")
        # Build an args summary to embed into the lab description (no secrets)
        args_bits: list[str] = [f"nodes={total}", f"-m {args.mode}", f"-T {args.template}"]
        dev_def = getattr(args, "dev_template", args.template)
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        if getattr(args, "enable_vrf", False):
            args_bits.append("--vrf")
            if getattr(args, "pair_vrf", None):
                args_bits.append(f"--pair-vrf {args.pair_vrf}")
        args_bits.append(f"--flat-group-size {args.flat_group_size}")
        if getattr(args, "loopback_255", False):
            args_bits.append("--loopback-255")
        if getattr(args, "gi0_zero", False):
            args_bits.append("--gi0-zero")
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        version = getattr(args, "cml_version", "0.3.0")
        if version:
            args_bits.append(f"--cml-version {version}")
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, flat-pair) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f'  description: "{desc}"')
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        lines.append("nodes:")

        node_ids: dict[str, str] = {}
        nid = 0
        # Core switch
        node_ids["SW0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SW0']}")
        lines.append("    label: SW0")
        lines.append("    node_definition: unmanaged_switch")
        lines.append("    x: 0")
        lines.append("    y: 0")

        # Determine router counts per access switch (same as flat)
        per_sw_counts: list[int] = []
        for i in range(num_sw):
            start = i * group + 1
            end = min((i + 1) * group, total)
            per_sw_counts.append(max(0, end - start + 1))

        # Core interfaces: one per access switch + 1 extra for CA-ROOT if --pki enabled
        sw0_port_count = num_sw
        if getattr(args, "pki_enabled", False):
            sw0_port_count += 1
        lines.append("    interfaces:")
        for p in range(sw0_port_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append(f"        type: physical")

        # Access switches
        access_if_start_slots: list[int] = []
        for i in range(num_sw):
            label = f"SW{i+1}"
            node_ids[label] = f"n{nid}"; nid += 1
            x = (i + 1) * args.distance * 3
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append("    node_definition: unmanaged_switch")
            lines.append(f"    x: {x}")
            lines.append("    y: 0")
            # 1 uplink + ports for all routers in the group (unchanged)
            if_count = 1 + per_sw_counts[i]
            lines.append("    interfaces:")
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append(f"        type: physical")
            access_if_start_slots.append(0)

        # OOB management switches (if --mgmt enabled) - mirrors access switch pattern
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            from math import ceil
            num_oob_sw = ceil(total / oob_group)
            # Precompute how many routers per OOB access switch
            for i in range(num_oob_sw):
                start = i * oob_group + 1
                end = min((i + 1) * oob_group, total)
                oob_per_sw_counts.append(max(0, end - start + 1))

            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            # Ports for OOB access switches + 1 extra for CA-ROOT if --pki enabled
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append(f"        type: physical")

            # OOB access switches
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * args.distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {(i + 1) * args.distance}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append(f"        type: physical")

        # Pre-compute /30 p2p addressing for odd-even pairs from cfg.p2pnets
        pair_ips_off: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = cfg.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            pair_ips_off[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        # Routers: include Gi0/0 for all; include Gi0/1 for odd routers only
        dev_def = getattr(args, "dev_template", args.template)
        g_base = "10.0" if getattr(args, "gi0_zero", False) else "10.10"
        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"
        for idx in range(total):
            n = idx + 1
            label = f"R{n}"
            node_ids[label] = f"n{nid}"; nid += 1
            hi, lo = addr_parts(n)
            g_ip = f"{g_base}.{hi}.{lo}"
            l_ip = f"{l_base}.{hi}.{lo}"

            # Render configuration using the same template logic as online path
            # Offline config mirrors online behavior with optional p2p IPs
            if n % 2 == 1:
                odd_ip = pair_ips_off.get(n, (None, None))[0]
                pair_vrf = (
                    getattr(args, "pair_vrf", None)
                    if getattr(args, "enable_vrf", False)
                    else None
                )
                ifaces = [
                    TopogenInterface(
                        address=IPv4Interface(f"{g_ip}/16"), description="mgmt flat-pair", slot=0
                    ),
                    TopogenInterface(
                        address=odd_ip,
                        vrf=pair_vrf,
                        description="pair link",
                        slot=1,
                    ),
                ]
            else:
                even_ip = pair_ips_off.get(n - 1, (None, None))[1]
                ifaces = [TopogenInterface(address=even_ip, description="pair link", slot=0)]

            node = TopogenNode(
                hostname=label,
                loopback=IPv4Interface(f"{l_ip}/32"),
                interfaces=ifaces,
            )
            # Build mgmt/ntp context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            rendered = tpl.render(
                config=cfg,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
            )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )

            rx = (idx // group + 1) * args.distance * 3
            ry = (idx % group + 1) * args.distance
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {rx}")
            lines.append(f"    y: {ry}")
            lines.append("    interfaces:")
            def iface_label_for_slot(slot: int) -> str:
                # CML node definitions can have different interface naming.
                # csr1000v typically uses GigabitEthernet1, GigabitEthernet2, ...
                if str(dev_def).lower() == "csr1000v":
                    return f"GigabitEthernet{slot + 1}"
                return f"GigabitEthernet0/{slot}"

            # Always slot 0
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append(f"        label: {iface_label_for_slot(0)}")
            lines.append("        type: physical")
            # Odd routers have slot 1 for the pair link
            if n % 2 == 1:
                lines.append("      - id: i1")
                lines.append("        slot: 1")
                lines.append(f"        label: {iface_label_for_slot(1)}")
                lines.append("        type: physical")
            # Mgmt interface (if --mgmt enabled)
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in rendered.splitlines():
                lines.append(f"      {ln}")

        # CA-ROOT node (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1

            # CA gets last usable IP in the flat CIDR (e.g. 10.10.255.254/16), same as flat mode
            ca_loopback_ip = f"{l_base}.255.254"
            ca_data_ip = f"{g_base}.255.254"

            # Create CA node with data interface (connects to SW0)
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=IPv4Interface(f"{ca_loopback_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{ca_data_ip}/16"),
                        description="=== SCEP Enrollment URL ===",
                        slot=0,
                    )
                ],
            )

            # Build CA config using same template selection logic as offline_flat_yaml
            # Determine which CSR template to use based on regular router template
            template_name = getattr(args, "template", "iosv")
            if "ospf" in template_name or template_name == "iosv":
                ca_template_name = "csr-ospf"
            elif "eigrp" in template_name:
                ca_template_name = "csr-eigrp"
            else:
                ca_template_name = "csr-eigrp"

            try:
                ca_base_tpl = env.get_template(f"{ca_template_name}{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                raise TopogenError(f"CA template not found: {ca_template_name}")

            # Render base config with routing protocol
            ca_mgmt_ctx = None
            if enable_mgmt:
                ca_mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(args, "mgmt_vrf", None),
                    "gw": getattr(args, "mgmt_gw", None),
                }
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
            )

            # Append PKI-specific config
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "ip http secure-server",
                "ip http secure-server trustpoint CA-ROOT-SELF",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]

            ca_config_lines = ca_base_config.splitlines()

            # Replace generic RSA key with named key (needed for PKI server)
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"

            # PKI block before EEM so double end/end does not quit config too soon
            ca_scep_url = f"http://{ca_data_ip}:80"
            insert_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + _pki_ca_authenticate_eem_lines()
            )
            try:
                end_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip() == "end")
                ca_config_lines[end_idx:end_idx] = insert_block
            except StopIteration:
                ca_config_lines.extend(insert_block)

            ca_rendered = "\n".join(ca_config_lines)

            # Place CA near SW0 (core switch area)
            ca_x = -400
            ca_y = 200

            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append("    node_definition: csr1000v")  # CA is always CSR
            lines.append(f"    x: {ca_x}")
            lines.append(f"    y: {ca_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                ca_mgmt_slot_id = mgmt_slot - 1  # CA is always CSR, so slot-1
                lines.append(f"      - id: i{ca_mgmt_slot_id}")
                lines.append(f"        slot: {ca_mgmt_slot_id}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            lines.append("    configuration: |-")
            for ln in ca_rendered.splitlines():
                lines.append(f"      {ln}")

        # Links
        lines.append("links:")
        lid = 0
        # Access -> core
        for i in range(num_sw):
            acc = f"SW{i+1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[acc]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{i}")

        # CA-ROOT -> SW0 data link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # SW0's next available port after access switches
            sw0_ca_port = num_sw
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{sw0_ca_port}")

        # Router -> access switch (only odd routers connect Gi0/0 to access switch)
        router_sw_port: dict[str, tuple[str, int]] = {}
        per_sw_next_port = [1 for _ in range(num_sw)]  # reserve 0 for uplink
        for idx in range(total):
            n = idx + 1
            if n % 2 == 0:
                continue  # even routers do not connect to access switch
            rlabel = f"R{n}"
            sw_index = idx // group + 1
            acc = f"SW{sw_index}"
            acc_port = per_sw_next_port[sw_index - 1]
            per_sw_next_port[sw_index - 1] += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[acc]}")
            lines.append(f"    i2: i{acc_port}")

        # Odd-even pairing links: R1 i1 <-> R2 i0, R3 i1 <-> R4 i0, ...
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                break
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[f'R{odd}']}")
            lines.append("    i1: i1")
            lines.append(f"    n2: {node_ids[f'R{even}']}")
            lines.append("    i2: i0")

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for idx in range(total):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                # CA is always CSR1000v, so use slot - 1
                ca_mgmt_iface_id = mgmt_slot - 1
                # SWoob0's next available port after ext-conn-mgmt (if present) and OOB access switches
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

        outfile = Path(getattr(args, "offline_yaml"))
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _intent_annotation_lines(desc) + lines
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (flat-pair) written to %s (%.1f KB)", outfile, size_kb)
        return 0
    def render_flat_network(self) -> int:
        """Render a flat L2 management network.

        - Create unmanaged switches, each serving up to args.flat_group_size routers.
        - Connect all unmanaged switches to a core to keep one broadcast domain (star).
        - Connect each router's Gig0/0 (slot 0) to its group's switch.
        - Do not assign IPs to interfaces; users will enable EIGRP on Gig0 later.
        """

        disable_pcl_loggers()

        total = self.args.nodes
        group = max(1, int(self.args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)

        # Warn about custom device templates/images which may affect interface behavior
        dev_def = getattr(self.args, "dev_template", self.args.template)
        if dev_def != "iosv":
            _LOGGER.warning(
                "Using custom device template '%s'; guardrails assume ~32-port unmanaged_switch and do not account for custom node definitions/images",
                dev_def,
            )

        _LOGGER.warning("Creating %d unmanaged switches for %d routers (group size %d)", num_sw, total, group)

        # Core switch in the middle
        core = self.create_node("SW0", "unmanaged_switch", Point(0, 0))

        # OOB management switch (if --mgmt enabled)
        enable_mgmt = getattr(self.args, "enable_mgmt", False)
        mgmt_slot = getattr(self.args, "mgmt_slot", 5)
        oob_switch = None
        mgmt_ext_conn = None
        if enable_mgmt:
            oob_switch = self.create_node("SWoob0", "unmanaged_switch", Point(-200, 0))
            if hasattr(oob_switch, "hide_links"):
                oob_switch.hide_links = True

            # Create external connector for management bridge (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(self.args, "mgmt_bridge", False)
            if mgmt_bridge:
                mgmt_ext_conn = self.create_node("ext-conn-mgmt", "external_connector", Point(-440, 0))
                mgmt_ext_conn.configuration = "System Bridge"
                self.lab.create_link(
                    mgmt_ext_conn.get_interface_by_slot(0),
                    oob_switch.get_interface_by_slot(0),
                )
                _LOGGER.warning("Management external connector: %s", mgmt_ext_conn.label)

        # Create access switches positioned horizontally
        switches: list[Node] = []
        for i in range(num_sw):
            x = (i + 1) * self.args.distance * 3
            sw = self.create_node(f"SW{i+1}", "unmanaged_switch", Point(x, 0))
            switches.append(sw)
            # Connect each access switch back to core (star)
            self.lab.create_link(self.new_interface(core), self.new_interface(sw))
            _LOGGER.info("switch-link: %s <-> %s", core.label, sw.label)

        # Create routers and attach Gig0/0 to the appropriate switch
        for idx in range(total):
            router_label = f"R{idx + 1}"
            # Stagger routers below their switch
            sw_index = idx // group
            rx = (sw_index + 1) * self.args.distance * 3
            ry = (idx % group + 1) * self.args.distance
            cml_router = self.create_router(router_label, Point(rx, ry))

            # Ensure we have an interface on router and switch, then link them
            try:
                r_if = cml_router.get_interface_by_slot(0)
            except Exception:  # pragma: no cover - defensive
                r_if = self.new_interface(cml_router)

            sw = switches[sw_index]
            s_if = self.new_interface(sw)
            self.lab.create_link(r_if, s_if)
            _LOGGER.info("link: %s Gi0/0 -> %s", cml_router.label, sw.label)

            # Connect mgmt interface to OOB switch if enabled
            if enable_mgmt and oob_switch is not None:
                dev_def = getattr(self.args, "dev_template", self.args.template)
                router_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                try:
                    mgmt_if = cml_router.get_interface_by_slot(router_mgmt_slot)
                except Exception:
                    mgmt_if = cml_router.create_interface(slot=router_mgmt_slot)
                oob_if = self.new_interface(oob_switch)
                self.lab.create_link(mgmt_if, oob_if)
                _LOGGER.info("mgmt-link: %s slot %d -> %s", cml_router.label, router_mgmt_slot, oob_switch.label)

            # Deterministic addressing (1-based index encoded in last 16 bits)
            ridx = idx + 1
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            g_addr = IPv4Interface(f"{g_base}.{hi}.{lo}/16")
            l_addr = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            # Build mgmt context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(self.args, "mgmt_vrf", None),
                    "gw": getattr(self.args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            # Build config: Loopback0 and Gi0/0 with assigned addresses
            node = TopogenNode(
                hostname=router_label,
                loopback=l_addr,
                interfaces=[TopogenInterface(address=g_addr, description="mgmt flat", slot=0)],
            )
            config = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
            )
            cml_router.configuration = config  # type: ignore[method-assign]

        # Create PKI Root CA router if --pki enabled
        if getattr(self.args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # Position CA to the left of SW0
            ca_pos = Point(-self.args.distance * 3, 0)
            ca_router = self.create_router(ca_label, ca_pos)

            # Connect CA to core switch (SW0) on slot 0
            ca_if = ca_router.get_interface_by_slot(0)
            core_if = self.new_interface(core)
            self.lab.create_link(ca_if, core_if)
            _LOGGER.info("CA link: %s Gi0/0 -> %s", ca_label, core.label)

            # Connect CA to OOB switch if enabled
            if enable_mgmt and oob_switch is not None:
                dev_def = getattr(self.args, "dev_template", self.args.template)
                ca_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                try:
                    ca_mgmt_if = ca_router.get_interface_by_slot(ca_mgmt_slot)
                except Exception:
                    ca_mgmt_if = ca_router.create_interface(slot=ca_mgmt_slot)
                oob_ca_if = self.new_interface(oob_switch)
                self.lab.create_link(ca_mgmt_if, oob_ca_if)
                _LOGGER.info("CA mgmt-link: %s slot %d -> %s", ca_label, ca_mgmt_slot, oob_switch.label)

            # Assign last usable IP in the flat CIDR (e.g., 10.10.255.254/16)
            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            ca_g_addr = IPv4Interface(f"{g_base}.255.254/16")
            ca_l_addr = IPv4Interface(f"{l_base}.255.254/32")

            # Build mgmt/ntp context for CA
            ca_mgmt_ctx = None
            if enable_mgmt:
                ca_mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(self.args, "mgmt_vrf", None),
                    "gw": getattr(self.args, "mgmt_gw", None),
                }
            ca_ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            # Build config using csr-pki-ca template
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=ca_l_addr,
                interfaces=[TopogenInterface(address=ca_g_addr, description="=== SCEP Enrollment URL ===", slot=0)],
            )
            # Load csr-pki-ca template (no trim_blocks/lstrip_blocks to preserve newlines)
            import jinja2
            from pathlib import Path
            template_dir = Path(__file__).parent / "templates"
            ca_template = jinja2.Environment(
                loader=jinja2.FileSystemLoader(template_dir),
            ).get_template("csr-pki-ca.jinja2")

            ca_config = ca_template.render(
                config=self.config,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
                pki_ca_key="",  # Empty for now; will be filled once key is exported
                pki_enrollment_url=str(ca_g_addr.ip),  # CA's own data interface IP
            )
            ca_router.configuration = ca_config  # type: ignore[method-assign]
            _LOGGER.warning("PKI Root CA created: %s at %s", ca_label, ca_g_addr.ip)

        _LOGGER.warning("Flat management network created")
        # Get lab definition size (and optionally export to file) so we can log size for online create
        outfile = getattr(self.args, "yaml_output", None)
        content = None
        try:
            if hasattr(self.client, "export_lab"):
                content = self.client.export_lab(self.lab.id)  # type: ignore[attr-defined]
            elif hasattr(self.lab, "export"):
                content = self.lab.export()  # type: ignore[attr-defined]
            elif hasattr(self.lab, "topology"):
                content = str(self.lab.topology)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - best-effort
            pass
        if content is not None:
            data = content if isinstance(content, bytes) else str(content).encode("utf-8")
            size_kb = len(data) / 1024
            _LOGGER.warning("Lab created (%.1f KB) - uploaded to controller", size_kb)
            if outfile:
                try:
                    with open(outfile, "wb") as fh:
                        fh.write(data)
                    _LOGGER.warning("Exported lab YAML to %s", outfile)
                except Exception as exc:  # pragma: no cover
                    _LOGGER.error("YAML export failed: %s", exc)
        else:
            _LOGGER.warning("Lab created - uploaded to controller")

        # Print lab URL
        import os
        base_url = os.environ.get('VIRL2_URL', self.client.url if hasattr(self.client, 'url') else 'http://localhost').rstrip('/')
        _LOGGER.warning(f"Lab URL: {base_url}/lab/{self.lab.id}")

        # Start lab if requested (non-blocking)
        _start_lab_in_background(self.lab, self.args)

        return 0

    def render_node_sequence(self):
        """render the square spiral / node sequence network. Note: due to TTL
        limitations, it does not make a lot of sense to have this larger than
        32 or so hosts if end-to-end connectivity is required... One can still
        hop hop-by-hop, but DNS won't work all the way back to the DNS host!
        """

        disable_pcl_loggers()
        prev_iface = None
        prev_cml2iface = None

        if self.args.progress:
            manager = enlighten.get_manager(coords=next(self.coords))
            ticks = manager.counter(
                total=self.args.nodes,
                desc="Progress",
                unit="nodes",
                color="cyan",
                leave=False,
            )

        # create the external connector
        cml2_node = self.create_ext_conn()
        _LOGGER.info("external connector: %s", cml2_node.label)

        # create the DNS host
        dns_iface, prev_iface = self.next_network()
        dns_via = prev_iface
        dns_host = self.create_dns_host(coords=next(self.coords))
        _LOGGER.info("DNS host: %s", dns_host.label)
        prev_cml2iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_iface.ip)
        dns_zone: list[DNShost] = []

        # link the two
        self.lab.create_link(
            cml2_node.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.info("ext-conn link")

        # OOB management network (if --mgmt enabled)
        enable_mgmt = getattr(self.args, "enable_mgmt", False)
        mgmt_slot = getattr(self.args, "mgmt_slot", 5)
        oob_switch = None
        mgmt_ext_conn = None
        if enable_mgmt:
            # Create OOB management switch (use explicit coords to avoid spiral generator issues)
            oob_switch = self.create_node("SWoob0", "unmanaged_switch", Point(-200, 0))
            if hasattr(oob_switch, "hide_links"):
                oob_switch.hide_links = True
            _LOGGER.warning("OOB management switch: %s", oob_switch.label)

            # Create external connector for management bridge (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(self.args, "mgmt_bridge", False)
            if mgmt_bridge:
                mgmt_ext_conn = self.create_node("ext-conn-mgmt", "external_connector", Point(-440, 0))
                mgmt_ext_conn.configuration = "System Bridge"
                _LOGGER.warning("Management external connector: %s", mgmt_ext_conn.label)
                # Link external connector to OOB switch
                self.lab.create_link(
                    mgmt_ext_conn.get_interface_by_slot(0),
                    oob_switch.get_interface_by_slot(0),
                )
                _LOGGER.warning("Creating mgmt ext-conn link")

        for idx in range(self.args.nodes):
            loopback = IPv4Interface(next(self.loopbacks))
            src_iface, dst_iface = self.next_network()
            interfaces = [
                TopogenInterface(address=src_iface),
                TopogenInterface(address=prev_iface),
            ]
            node = TopogenNode(
                hostname=f"R{idx + 1}",
                loopback=loopback,
                interfaces=interfaces,
            )

            # Build mgmt context for template
            mgmt_ctx = None
            if enable_mgmt:
                mgmt_ctx = {
                    "enabled": True,
                    "slot": mgmt_slot,
                    "vrf": getattr(self.args, "mgmt_vrf", None),
                    "gw": getattr(self.args, "mgmt_gw", None),
                }
            ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            config = self.template.render(
                config=self.config,
                node=node,
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
            )
            node_def = getattr(self.args, "dev_template", self.args.template)
            cml2_node = self.create_node(
                node.hostname, node_def, next(self.coords)
            )
            cml2_node.config = config
            _LOGGER.info("node: %s", cml2_node.label)
            self.lab.create_link(prev_cml2iface, cml2_node.get_interface_by_slot(1))
            _LOGGER.info("link %s", prev_cml2iface.label)
            prev_cml2iface = cml2_node.get_interface_by_slot(0)

            # Connect mgmt interface to OOB switch if enabled
            if enable_mgmt and oob_switch is not None:
                dev_def = getattr(self.args, "dev_template", self.args.template)
                router_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                # Always create a new interface for management at the specified slot
                mgmt_if = cml2_node.create_interface(slot=router_mgmt_slot)
                oob_if = self.new_interface(oob_switch)
                self.lab.create_link(mgmt_if, oob_if)
                _LOGGER.warning("mgmt-link: %s slot %d -> %s", cml2_node.label, router_mgmt_slot, oob_switch.label)
            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            prev_iface = dst_iface
            if self.args.progress:
                ticks.update()  # type: ignore

        # finalize the DNS host configuration
        node = TopogenNode(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                TopogenInterface(address=dns_iface),
                TopogenInterface(address=dns_via),
            ],
        )
        dns_host.config = dnshostconfig(self.config, node, dns_zone)

        if self.args.progress:
            ticks.close()  # type: ignore
            manager.stop()  # type: ignore

        # Print lab URL
        import os
        base_url = os.environ.get('VIRL2_URL', self.client.url if hasattr(self.client, 'url') else 'http://localhost').rstrip('/')
        _LOGGER.warning(f"Lab URL: {base_url}/lab/{self.lab.id}")

        # Start lab if requested (non-blocking)
        _start_lab_in_background(self.lab, self.args)

        return 0
