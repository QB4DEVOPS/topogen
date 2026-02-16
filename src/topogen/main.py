# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
#
"""
TopoGen Main Entry Point - CLI Argument Parsing and Application Bootstrap

PURPOSE:
    Entry point for the topogen CLI tool. Handles argument parsing, validation,
    configuration loading, and orchestrates the rendering pipeline based on user inputs.

WHO READS ME:
    - Users: via CLI command `topogen` or `python -m topogen.main`
    - gui.py: when launching GUI mode with Gooey

WHO I READ:
    - config.py: Configuration loading and defaults
    - models.py: TopogenError exception handling
    - render.py: Renderer class and topology generation functions
    - colorlog.py: Custom log formatting

DEPENDENCIES:
    - argparse: CLI argument parsing
    - logging: Application logging
    - os, sys: System operations

KEY EXPORTS:
    - main(): Application entry point
    - create_argparser(): Creates and configures the argument parser
    - valid_node_count(): Validates node count argument (2-1000)

FLOW:
    1. Parse CLI arguments (create_argparser)
    2. Load configuration from config.toml (or defaults)
    3. Validate arguments (node count, IP addresses, flag dependencies)
    4. Create Renderer instance based on mode (nx, simple, flat, flat-pair, dmvpn)
    5. Execute online (CML API) or offline (YAML generation) workflow
"""

import argparse
import logging
import os
import sys

import topogen
from topogen.models import TopogenError
from topogen.render import Renderer, get_templates
from topogen.colorlog import CustomFormatter

_LOGGER = logging.getLogger(__name__)


def valid_node_count(value):
    ivalue = int(value)
    if ivalue < 2 or ivalue > 1000:
        raise argparse.ArgumentTypeError(
            f"invalid value {value}. Valid values are from 2-1000."
        )
    return ivalue


def create_argparser(parser_class=argparse.ArgumentParser):
    """create the argparser for topogen"""
    parser = parser_class(
        prog=topogen.__name__, description=topogen.__description__
    )
    is_gooey = getattr(parser_class, "__name__", "") == "GooeyParser"
    config_settings = parser.add_argument_group("configuration")

    config_settings.add_argument(
        "-c",
        "--config",
        dest="configfile",
        help="Use the configuration from this file, defaults to %(default)s",
        default="config.toml",
    )
    config_settings.add_argument(
        "-w",
        "--write",
        dest="writeconfig",
        action="store_true",
        help="Write the default configuration to a file and exit",
        default=False,
    )
    config_settings.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {topogen.__version__}"
    )
    config_settings.add_argument(
        "-l",
        "--loglevel",
        type=str,
        default=os.environ.get("LOG_LEVEL", "WARN"),
        help="DEBUG, INFO, WARN, ERROR, CRITICAL, defaults to %(default)s",
    )
    config_settings.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="show a progress bar",
    )

    parser.add_argument(
        "--ca",
        dest="cafile",
        help="Use the CA certificate from this file (PEM format), defaults to %(default)s",
        default="ca.pem",
    )
    parser.add_argument(
        "-i",
        "--insecure",
        action="store_true",
        help="If no CA provided, do not verify TLS (insecure!)",
        default=False,
    )
    parser.add_argument(
        "-d",
        "--distance",
        type=int,
        default=200,
        help="Node distance, default %(default)d",
    )
    parser.add_argument(
        "-L",
        "--labname",
        type=str,
        default="topogen lab",
        help='Lab name to create, default "%(default)s"',
    )
    parser.add_argument(
        "-R",
        "--remark",
        type=str,
        default=None,
        help="Add a custom remark/note to the lab description (optional)",
    )
    if is_gooey:
        parser.add_argument(
            "-T",
            "--template",
            type=str,
            choices=get_templates(),
            help='Template name to use, defaults to "%(default)s"',
            default="iosv",
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "-T",
            "--template",
            type=str,
            help='Template name to use, defaults to "%(default)s"',
            default="iosv",
        )
    if is_gooey:
        parser.add_argument(
            "--device-template",
            dest="dev_template",
            type=str,
            choices=("iosv", "csr1000v", "iol", "lxc"),
            default="iosv",
            help='CML node definition to use for routers (e.g., iosv, iol, lxc). Defaults to "%(default)s"',
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "--device-template",
            dest="dev_template",
            type=str,
            default="iosv",
            help='CML node definition to use for routers (e.g., iosv, iol, lxc). Defaults to "%(default)s"',
        )
    parser.add_argument(
        "--list-templates",
        dest="listtemplates",
        action="store_true",
        help="List all available templates",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=("nx", "simple", "flat", "flat-pair", "dmvpn"),
        default="simple",
        help='mode of operation, default is "%(default)s"',
    )

    parser.add_argument(
        "--dmvpn-phase",
        dest="dmvpn_phase",
        type=int,
        choices=(2, 3),
        default=2,
        help='DMVPN phase (2 or 3), default %(default)d',
    )
    parser.add_argument(
        "--dmvpn-routing",
        dest="dmvpn_routing",
        type=str,
        choices=("eigrp", "ospf"),
        default="eigrp",
        help='Routing protocol over DMVPN tunnel, default "%(default)s"',
    )
    parser.add_argument(
        "--eigrp-stub",
        dest="eigrp_stub",
        action="store_true",
        default=False,
        help="Enable EIGRP stub (connected summary) on selected routers (DMVPN flat-pair: even routers)",
    )
    parser.add_argument(
        "--dmvpn-security",
        dest="dmvpn_security",
        type=str,
        choices=("none", "ikev2-psk", "ikev2-pki"),
        default="none",
        help='DMVPN security: none, ikev2-psk (requires --dmvpn-psk), ikev2-pki (requires --pki), default "%(default)s"',
    )
    parser.add_argument(
        "--dmvpn-psk",
        dest="dmvpn_psk",
        type=str,
        default=None,
        help="DMVPN IKEv2 pre-shared key (used when --dmvpn-security ikev2-psk)",
    )
    if is_gooey:
        parser.add_argument(
            "--dmvpn-underlay",
            dest="dmvpn_underlay",
            type=str,
            choices=("flat", "flat-pair"),
            default="flat",
            help='DMVPN underlay topology, default "%(default)s"',
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "--dmvpn-underlay",
            dest="dmvpn_underlay",
            type=str,
            choices=("flat", "flat-pair"),
            default="flat",
            help='DMVPN underlay topology, default "%(default)s"',
        )
    parser.add_argument(
        "--dmvpn-nbma-cidr",
        dest="dmvpn_nbma_cidr",
        type=str,
        default="10.10.0.0/16",
        help='NBMA underlay CIDR for DMVPN WAN segment, default "%(default)s"',
    )
    parser.add_argument(
        "--dmvpn-tunnel-cidr",
        dest="dmvpn_tunnel_cidr",
        type=str,
        default="172.20.0.0/16",
        help='Tunnel overlay CIDR for DMVPN Tunnel0 addressing, default "%(default)s"',
    )
    if is_gooey:
        parser.add_argument(
            "--dmvpn-tunnel-key",
            dest="dmvpn_tunnel_key",
            type=int,
            default=10,
            help='DMVPN Tunnel0 key (GRE tunnel key), default %(default)d',
            gooey_options={"widget": "IntegerField"},
        )
        parser.add_argument(
            "--dmvpn-hubs",
            dest="dmvpn_hubs",
            type=str,
            default=None,
            help="Comma-separated router numbers to act as DMVPN hubs (e.g., 1,21,41). When set, the nodes argument is interpreted as total routers.",
            gooey_options={"widget": "TextField"},
        )
    else:
        parser.add_argument(
            "--dmvpn-tunnel-key",
            dest="dmvpn_tunnel_key",
            type=int,
            default=10,
            help='DMVPN Tunnel0 key (GRE tunnel key), default %(default)d',
        )
        parser.add_argument(
            "--dmvpn-hubs",
            dest="dmvpn_hubs",
            type=str,
            default=None,
            help="Comma-separated router numbers to act as DMVPN hubs (e.g., 1,21,41). When set, the nodes argument is interpreted as total routers.",
        )
    parser.add_argument(
        "--flat-group-size",
        dest="flat_group_size",
        type=int,
        default=20,
        help="Routers per unmanaged switch when using flat mode, default %(default)d",
    )
    parser.add_argument(
        "--loopback-255",
        dest="loopback_255",
        action="store_true",
        help="Use 10.255.C.D/32 for Loopback0 addressing in flat mode (default is 10.20.C.D/32)",
    )
    parser.add_argument(
        "--gi0-zero",
        dest="gi0_zero",
        action="store_true",
        help="Use 10.0.C.D/16 for Gi0/0 addressing in flat mode (default is 10.10.C.D/16)",
    )
    parser.add_argument(
        "--vrf",
        dest="enable_vrf",
        action="store_true",
        help="Enable VRF configuration (applies to flat-pair odd-router Gi0/1 when combined with --pair-vrf)",
        default=False,
    )
    parser.add_argument(
        "--pair-vrf",
        dest="pair_vrf",
        type=str,
        default="tenant",
        help='VRF name to apply to the flat-pair odd-router Gi0/1 (pair link), default "%(default)s"',
    )
    parser.add_argument(
        "--mgmt",
        dest="enable_mgmt",
        action="store_true",
        default=False,
        help="Enable a dedicated OOB management network (SWmgmt0 + router mgmt interfaces)",
    )
    parser.add_argument(
        "--mgmt-cidr",
        dest="mgmt_cidr",
        type=str,
        default="10.254.0.0/16",
        help='Management network CIDR, default "%(default)s"',
    )
    parser.add_argument(
        "--mgmt-gw",
        dest="mgmt_gw",
        type=str,
        default=None,
        help="Management network gateway IP (optional); adds a default route in the mgmt VRF if set",
    )
    parser.add_argument(
        "--mgmt-slot",
        dest="mgmt_slot",
        type=int,
        default=5,
        help="Interface slot for management (IOSv Gi0/N, CSR GiN), default %(default)d",
    )
    parser.add_argument(
        "--mgmt-vrf",
        dest="mgmt_vrf",
        type=str,
        default="Mgmt-vrf",
        help='VRF name for management interface (default: "%(default)s"); use "global" for global routing table',
    )
    parser.add_argument(
        "--mgmt-bridge",
        dest="mgmt_bridge",
        action="store_true",
        default=False,
        help="Add external-connector to bridge OOB management network to external network (requires --mgmt)",
    )
    parser.add_argument(
        "--ntp",
        dest="ntp_server",
        type=str,
        default=None,
        help="NTP server IP address (optional)",
    )
    parser.add_argument(
        "--ntp-vrf",
        dest="ntp_vrf",
        type=str,
        default=None,
        help="VRF for NTP source interface; uses mgmt VRF if not specified and --mgmt-vrf is set",
    )
    parser.add_argument(
        "--ntp-inband",
        dest="ntp_inband",
        action="store_true",
        default=False,
        help="Put --ntp server in global (inband); no VRF. Use when CA is NTP server on data network.",
    )
    parser.add_argument(
        "--ntp-oob",
        dest="ntp_oob_server",
        type=str,
        default=None,
        help="Optional second NTP server in mgmt VRF (e.g. external NTP). Use with --mgmt.",
    )
    parser.add_argument(
        "--pki",
        dest="pki_enabled",
        action="store_true",
        default=False,
        help="Enable PKI Root CA (adds CA-ROOT router for certificate services)",
    )
    parser.add_argument(
        "--pki-enroll",
        dest="pki_enroll_mode",
        type=str,
        choices=["scep", "cli"],
        default="scep",
        help="PKI enrollment mode: scep (auto via SCEP) or cli (manual CLI enrollment for external CA)",
    )
    parser.add_argument(
        "--start",
        dest="start_lab",
        action="store_true",
        default=False,
        help="Automatically start the lab after creation",
    )
    if is_gooey:
        parser.add_argument(
            "--yaml",
            dest="yaml_output",
            metavar="ONLINE_EXPORT_YAML_FILE",
            type=str,
            help="Export the created lab to a YAML file at ONLINE_EXPORT_YAML_FILE",
            gooey_options={"widget": "FileSaver"},
        )
        parser.add_argument(
            "--offline-yaml",
            dest="offline_yaml",
            metavar="OFFLINE_YAML_FILE",
            type=str,
            help="Generate a CML-compatible YAML locally (no controller required)",
            gooey_options={"widget": "FileSaver"},
        )
    else:
        parser.add_argument(
            "--yaml",
            dest="yaml_output",
            metavar="FILE",
            type=str,
            help="Export the created lab to a YAML file at FILE",
        )
        parser.add_argument(
            "--offline-yaml",
            dest="offline_yaml",
            metavar="FILE",
            type=str,
            help="Generate a CML-compatible YAML locally (no controller required)",
        )
    parser.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting an existing output file when using --offline-yaml",
    )
    parser.add_argument(
        "--import-yaml",
        dest="import_yaml",
        metavar="FILE",
        type=str,
        help="Path to existing offline YAML to import (skip generation); use with --import",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        default=False,
        help="Import the generated or specified YAML into CML (requires --offline-yaml or --import-yaml)",
    )
    parser.add_argument(
        "--up",
        dest="up",
        metavar="FILE",
        type=str,
        help="Shorthand for --import-yaml FILE --import --start (import YAML to CML and start lab)",
    )
    parser.add_argument(
        "--print-up-cmd",
        dest="print_up_cmd",
        action="store_true",
        default=False,
        help="With --offline-yaml, print the topogen --up <file> command to run later",
    )
    parser.add_argument(
        "--cml-version",
        dest="cml_version",
        type=str,
        default="0.3.0",
        choices=[
            "0.0.1",
            "0.0.2",
            "0.0.3",
            "0.0.4",
            "0.0.5",
            "0.1.0",
            "0.2.0",
            "0.2.1",
            "0.2.2",
            "0.3.0",
        ],
        help="CML lab schema version for offline YAML (CML 2.9 uses 0.3.0)",
    )
    parser.add_argument(
        "nodes",
        nargs="?",
        type=valid_node_count,
        help="Number of nodes to generate (2-1000)",
    )
    parser.add_argument(
        "--allow-oversubscribe",
        dest="allow_oversubscribe",
        action="store_true",
        help="Bypass the recommended 520-node lab limit (use with caution)",
    )
    return parser


def get_log_level(level_name: str) -> tuple[int, bool]:
    log_levels = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    level_name = level_name.upper()
    if level_name in log_levels:
        return log_levels[level_name], False
    else:
        return logging.WARNING, True


def setup_logging(loglevel: str):
    """sets up the logging, takes the given loglevel and uses the custom,
    colorful log formatter
    """
    logging.basicConfig(level=logging.WARN)
    level, unknown_loglevel = get_log_level(loglevel)
    logging.root.setLevel(level)
    custom_formatter = CustomFormatter()
    for handler in logging.root.handlers:
        handler.setFormatter(custom_formatter)
    if unknown_loglevel:
        _LOGGER.warning("Unknown log level: %s", loglevel.upper())


def main():
    """main function, returns 0 on success, 1 otherwise"""
    parser = create_argparser()
    args = parser.parse_args()
    setup_logging(args.loglevel)

    def parse_dmvpn_hubs(value: str | None) -> list[int] | None:
        if value is None:
            return None
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
        if not raw:
            parser.error("Invalid --dmvpn-hubs: must provide at least one hub router number")
        hubs: list[int] = []
        for p in raw:
            try:
                hubs.append(int(p))
            except ValueError:
                parser.error(f"Invalid --dmvpn-hubs entry '{p}': must be an integer")
        if len(set(hubs)) != len(hubs):
            parser.error("Invalid --dmvpn-hubs: duplicate hub numbers are not allowed")
        return hubs

    cfg = topogen.Config.load(args.configfile)
    if args.writeconfig:
        cfg.save(args.configfile)
        return 0

    if args.insecure:
        args.cafile = None

    if args.listtemplates:
        print("Available templates: ", ", ".join(get_templates()))
        return 0

    try:
        args.dmvpn_hubs_list = parse_dmvpn_hubs(getattr(args, "dmvpn_hubs", None))

        if args.mode == "dmvpn" and getattr(args, "dmvpn_security", "none") == "ikev2-psk":
            psk = getattr(args, "dmvpn_psk", None)
            if not psk or not str(psk).strip():
                parser.error("--dmvpn-security ikev2-psk requires --dmvpn-psk <key>")
        if args.mode == "dmvpn" and getattr(args, "dmvpn_security", "none") == "ikev2-pki":
            if not getattr(args, "pki_enabled", False):
                parser.error("--dmvpn-security ikev2-pki requires --pki")

        # DMVPN flat-pair uses odd routers as DMVPN endpoints. If hubs are not
        # provided, default to the first 3 endpoint routers (R1,R3,R5), or fewer
        # if the lab is smaller.
        if args.mode == "dmvpn" and getattr(args, "dmvpn_underlay", "flat") == "flat-pair":
            if getattr(args, "dmvpn_hubs_list", None) is None:
                if not args.nodes:
                    parser.error("DMVPN requires nodes argument")
                max_odd_rnum = int(args.nodes) if (int(args.nodes) % 2) == 1 else (int(args.nodes) - 1)
                default_hubs = [h for h in (1, 3, 5) if h <= max_odd_rnum]
                args.dmvpn_hubs_list = default_hubs
                args.dmvpn_hubs = ",".join(str(h) for h in default_hubs)

        # Licensing / capacity guidance: soft cap at 520 unless bypassed
        if args.nodes and not getattr(args, "allow_oversubscribe", False) and args.nodes > 520:
            parser.error(
                f"nodes={args.nodes} exceeds the recommended maximum of 520 for typical enterprise licenses. "
                "Use --allow-oversubscribe to bypass this check if your environment supports more."
            )

        if args.mode == "dmvpn" and getattr(args, "dmvpn_hubs_list", None):
            if not args.nodes:
                parser.error("DMVPN requires nodes argument")
            hubs = args.dmvpn_hubs_list
            underlay = getattr(args, "dmvpn_underlay", "flat")
            if underlay == "flat-pair":
                total_routers = int(args.nodes)
                max_odd_rnum = total_routers if (total_routers % 2) == 1 else (total_routers - 1)
                out_of_range = [h for h in hubs if h < 1 or h > max_odd_rnum]
                if out_of_range:
                    bad = ",".join(str(h) for h in out_of_range)
                    parser.error(
                        "Invalid --dmvpn-hubs: hub router(s) "
                        f"{bad} do not exist as DMVPN endpoints in flat-pair (endpoints are odd routers R1..R{max_odd_rnum}; total routers R1..R{total_routers})"
                    )
            else:
                max_router = int(args.nodes)
                out_of_range = [h for h in hubs if h < 1 or h > max_router]
                if out_of_range:
                    bad = ",".join(str(h) for h in out_of_range)
                    parser.error(
                        f"Invalid --dmvpn-hubs: hub router(s) {bad} do not exist (lab has R1..R{max_router})"
                    )
        if args.mode == "dmvpn" and getattr(args, "dmvpn_underlay", "flat") == "flat-pair":
            hubs = getattr(args, "dmvpn_hubs_list", None)
            if hubs:
                even_hubs = [h for h in hubs if (h % 2) == 0]
                if even_hubs:
                    bad = ",".join(str(h) for h in even_hubs)
                    parser.error(
                        f"Invalid --dmvpn-hubs: hub router(s) {bad} are even-numbered, but DMVPN underlay 'flat-pair' uses odd routers as DMVPN endpoints"
                    )
        # Early validation for flat mode port assumptions
        if args.mode == "flat":
            if args.flat_group_size + 1 > 32:
                parser.error(
                    f"Invalid --flat-group-size {args.flat_group_size}: requires {args.flat_group_size + 1} ports per access switch (>32). Reduce --flat-group-size."
                )
            if args.nodes:
                from math import ceil

                if ceil(args.nodes / args.flat_group_size) > 32:
                    parser.error(
                        f"Invalid combination: nodes={args.nodes}, group_size={args.flat_group_size} requires more than 32 access switches (core ports). Increase --flat-group-size."
                    )
        # Validate mgmt flags
        if getattr(args, "enable_mgmt", False):
            from ipaddress import IPv4Network
            try:
                IPv4Network(args.mgmt_cidr, strict=False)
            except ValueError as exc:
                parser.error(f"Invalid --mgmt-cidr: {exc}")
            if args.mgmt_gw:
                from ipaddress import IPv4Address
                try:
                    IPv4Address(args.mgmt_gw)
                except ValueError as exc:
                    parser.error(f"Invalid --mgmt-gw: {exc}")
            # Normalize mgmt_vrf: treat "global" or empty as None (global table)
            if args.mgmt_vrf and args.mgmt_vrf.lower() == "global":
                args.mgmt_vrf = None
        # Validate mgmt-bridge requires mgmt
        if getattr(args, "mgmt_bridge", False) and not getattr(args, "enable_mgmt", False):
            parser.error("--mgmt-bridge requires --mgmt to be enabled")
        # Validate NTP flags
        if getattr(args, "ntp_server", None):
            from ipaddress import IPv4Address
            try:
                IPv4Address(args.ntp_server)
            except ValueError as exc:
                parser.error(f"Invalid --ntp: {exc}")
            # If ntp_vrf not set and OOB (--mgmt) is enabled, inherit mgmt_vrf (unless --ntp-inband).
            # Without --mgmt, NTP is inband so do not set ntp_vrf (no "ntp server vrf Mgmt-vrf").
            if not getattr(args, "ntp_inband", False):
                if (
                    not getattr(args, "ntp_vrf", None)
                    and getattr(args, "enable_mgmt", False)
                    and getattr(args, "mgmt_vrf", None)
                ):
                    args.ntp_vrf = args.mgmt_vrf
            else:
                args.ntp_vrf = None  # inband: no VRF for --ntp
            if getattr(args, "ntp_oob_server", None):
                from ipaddress import IPv4Address
                try:
                    IPv4Address(args.ntp_oob_server)
                except ValueError as exc:
                    parser.error(f"Invalid --ntp-oob: {exc}")
        # --up is shorthand for --import-yaml FILE --import --start (ignore empty string from GUI)
        up_val = getattr(args, "up", None)
        if up_val and str(up_val).strip():
            args.import_yaml = up_val.strip()
            args.do_import = True
            args.start_lab = True

        # --import requires a YAML source
        if getattr(args, "do_import", False):
            if not (getattr(args, "offline_yaml", None) or getattr(args, "import_yaml", None)):
                parser.error("--import requires --offline-yaml or --import-yaml")

        # Warn if --start used with --offline-yaml but not importing (start would do nothing)
        if (
            getattr(args, "start_lab", False)
            and getattr(args, "offline_yaml", None)
            and not getattr(args, "do_import", False)
        ):
            _LOGGER.warning("--start ignored: offline mode (--offline-yaml) does not create a lab on a controller; use --import to import then start")

        # Import-only path: existing YAML, no generation
        if getattr(args, "import_yaml", None) and getattr(args, "do_import", False):
            return Renderer.import_yaml_to_cml(args.import_yaml, args)

        # Offline YAML path: generate, then optionally import
        if getattr(args, "offline_yaml", None):
            if args.mode == "dmvpn":
                if getattr(args, "dmvpn_underlay", "flat") == "flat-pair":
                    retval = Renderer.offline_dmvpn_flat_pair_yaml(args, cfg)
                else:
                    retval = Renderer.offline_dmvpn_yaml(args, cfg)
            elif args.mode == "flat-pair":
                retval = Renderer.offline_flat_pair_yaml(args, cfg)
            else:
                retval = Renderer.offline_flat_yaml(args, cfg)
            if retval != 0:
                return retval
            if getattr(args, "do_import", False):
                return Renderer.import_yaml_to_cml(
                    args.offline_yaml, args, size_already_logged=True
                )
            if getattr(args, "print_up_cmd", False) and not getattr(args, "up", None):
                _LOGGER.warning(
                    "When you're ready: topogen --up %s",
                    args.offline_yaml.replace("\\", "/"),
                )
            return retval

        renderer = Renderer(args, cfg)
        # argparse ensures correct mode
        if args.mode == "simple":
            retval = renderer.render_node_sequence()
        elif args.mode == "nx":
            retval = renderer.render_node_network()
        elif args.mode == "flat":
            retval = renderer.render_flat_network()
        elif args.mode == "dmvpn":
            retval = renderer.render_dmvpn_network()
        else:  # args.mode == "flat-pair"
            retval = renderer.render_flat_pair_network()
    except TopogenError as exc:
        _LOGGER.error(exc)
        retval = 1
    return retval


if __name__ == "__main__":
    sys.exit(main())
