"""
a static topology generator
argument parsing and logging
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
        "--dmvpn-security",
        dest="dmvpn_security",
        type=str,
        choices=("none",),
        default="none",
        help='DMVPN security/profile, default "%(default)s"',
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
        # Licensing / capacity guidance: soft cap at 520 unless bypassed
        if args.nodes and not getattr(args, "allow_oversubscribe", False) and args.nodes > 520:
            parser.error(
                f"nodes={args.nodes} exceeds the recommended maximum of 520 for typical enterprise licenses. "
                "Use --allow-oversubscribe to bypass this check if your environment supports more."
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
        # Offline YAML path requires no controller
        if getattr(args, "offline_yaml", None):
            if args.mode == "dmvpn":
                return Renderer.offline_dmvpn_yaml(args, cfg)
            if args.mode == "flat-pair":
                return Renderer.offline_flat_pair_yaml(args, cfg)
            else:
                return Renderer.offline_flat_yaml(args, cfg)

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
