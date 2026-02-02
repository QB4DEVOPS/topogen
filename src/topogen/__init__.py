"""
TopoGen - CML2 Topology Generator

PURPOSE:
    TopoGen is a static topology generator for Cisco Modeling Labs (CML2).
    Generates network topologies with various modes (star, hierarchical, DMVPN)
    for testing, training, and network automation development.

PACKAGE STRUCTURE:
    - main.py: CLI entry point and argument parsing
    - render.py: Core topology generation and rendering logic
    - config.py: Configuration management
    - models.py: Data models (nodes, interfaces, coordinates)
    - dnshost.py: DNS host configuration generator
    - lxcfrr.py: FRR container configuration generator
    - colorlog.py: Colored log output formatter
    - gui.py: Optional Gooey-based GUI launcher
    - templates/: Jinja2 templates for router configurations

TOPOLOGY MODES:
    - Simple/NX: Star topology with central switch + DNS host
    - Flat: Hierarchical unmanaged switch fabric
    - Flat-pair: Odd-even router pairing with switch fabric
    - DMVPN: Hub-spoke DMVPN with flat or flat-pair underlay

OUTPUT MODES:
    - Online: Direct CML2 API integration (live lab creation)
    - Offline: YAML file generation (import into CML2 later)

MAIN ENTRY POINTS:
    - topogen: CLI command (calls main.main())
    - topogen-gui: GUI command (calls gui.main())
    - python -m topogen.main: Direct module execution

PUBLIC API:
    - Config: Configuration class
    - Renderer: Topology renderer class
    - main(): CLI entry point

VERSION:
    - __version__: Package version from metadata
    - __description__: Package description from metadata
"""

import importlib.metadata as importlib_metadata

from .config import Config
from .render import Renderer
from .main import main

_metadata = importlib_metadata.metadata("topogen")
__version__ = _metadata["Version"]
__description__ = _metadata["Summary"]


__all__ = ["Config", "Renderer", "main"]
