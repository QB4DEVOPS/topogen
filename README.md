# TopoGen for CML2

This package provides a `topogen` command which can create CML2 topologies.
It does this by using the PCL (VIRL Python Client Library) to talk to a live
controller, creating the lab, nodes and links on the fly.

![Demo](.images/demo.gif)

## Features

- create topologies of arbitrary size (up to 400 tested, this is N^2)
- can use templates to provide node configurations (currently a built-in
  DNS host template and an IOSv template exist)
- provide network numbering for all links (/30) and router loopbacks
- provide a DNS configuration so that all loopbacks and interface addresses can
  be resolved both from the DNS host as well as from all routers (provided the
  template configures DNS)
- provide a default route via DNS host, distributed via OSPF
- provide outbound NAT on the DNS host for the entire network
- flat L2 mode for large-scale labs (star of unmanaged switches with grouped routers)
- YAML export of generated labs via controller API
- offline YAML generation for CML (no controller needed) with `--offline-yaml`

## Code structure and dependencies

- **src/topogen/main.py**
  - CLI entrypoint. Parses arguments, sets up logging, loads config, and dispatches to the renderer.
  - Calls `Renderer.offline_flat_yaml()` for offline export, or constructs `Renderer` and calls one of:
    - `render_node_sequence()`
    - `render_node_network()`
    - `render_flat_network()`
  - Depends on: `topogen.Config`, `topogen.render.Renderer`, and templates by name.

- **src/topogen/render.py**
  - Authoritative topology logic and configuration rendering.
  - Online path uses `virl2_client` to create labs/nodes/links on a controller.
  - Offline path builds CML-compatible YAML (schema controlled by `--cml-version`).
  - Uses Jinja2 templates to render per-node configs and `Config` for settings.
  - Depends on: `virl2_client`, `jinja2`, `networkx` (for nx mode), `topogen.models`, and packaged templates.

- **src/topogen/templates/**
  - Jinja2 templates for device configuration.
  - `iosv.jinja2`: baseline IOSv config.
  - `iosv-eigrp.jinja2`: IOSv with EIGRP 100, SSH v2/RSA 2048, console no-timeout.
  - Referenced by name via `--template`; rendered by `render.py`.

- **src/topogen/config.py**
  - Defines `Config` (IP pools, credentials, defaults) loaded by `main.py` and used by `render.py`.

- **src/topogen/models.py**
  - Light data classes (`TopogenNode`, `TopogenInterface`, `Point`, etc.) and error types (`TopogenError`).
  - Consumed by `render.py` to pass structured data to templates and CML client.

- **src/topogen/__init__.py**
  - Package metadata and exposure of entrypoints.

Dependency flow (high level):

`main.py` → loads `Config` → selects template name → dispatches to `render.py` → `render.py` uses templates + config to build topology (online via `virl2_client` or offline YAML) → templates produce per-node configs.

## Installation

> **Important** Ensure that the PCL you install is compatible with your controller.
If it doesn't work, then try installing the wheel with Pip manually. The wheel can
be downloaded from your controller at the `/client` location.

Steps:

1. clone this directory
2. create virtual environment in it `python3 -mvenv .venv`
3. activate the venv `source .venv/bin/activate` (or with
   .fish or .bat, ...)
4. install using `python3 -mpip install -e .`

Alternatively, use Astral/uv:

1. clone this directory
2. create the venv: `uv venv`
3. activate the venv `source .venv/bin/activate` (optional, can also
   run with `uv run`)
4. install using `uv sync --frozen`

If the Networkx mode (`--mode nx`) should be used, then the following
command is required instead to install SciPy and NumPy dependencies: `uv sync
--all-extras --dev --frozen`

At this point, the `topogen` command should be available. Alternatively,
if you did not activate the venv, use `uv run topogen`.

## Configuration

### CML2

CML2 access is provided via the environment.  Like shown with this shell snippet:

```shell
VIRL2_URL="https://cml-controller.cml.lab"
VIRL2_USER="someuser"
VIRL2_PASS="somepass"
export VIRL2_URL VIRL2_USER VIRL2_PASS
```

In addition, a CA file in PEM format can be provided which can be used to verify
the cert presented by the controller... The default CA file of the controller is
included in the repo.

For this to work, it's also required to have proper name resolution for the CML2
controller (e.g. add `192.168.254.123 cml-controller.cml.lab` with **the correct
IP** into your hosts file).

### Tool

The tool accepts a variety of command line switches... they are all listed by
providing `-h` or `--help`:

```plain
$ topogen --help
usage: topogen [-h] [-c CONFIGFILE] [-w] [-v] [-l LOGLEVEL] [-p] [--ca CAFILE] [-i] [-d DISTANCE] [-L LABNAME] [-T TEMPLATE]
               [--device-template DEV_TEMPLATE] [--list-templates] [-m {nx,simple,flat}] [--flat-group-size FLAT_GROUP_SIZE]
               [--loopback-255] [--gi0-zero] [--yaml FILE] [--offline-yaml FILE]
               [--cml-version {0.0.1,0.0.2,0.0.3,0.0.4,0.0.5,0.1.0,0.2.0,0.2.1,0.2.2,0.3.0}] [nodes]

generate test topology files and configurations for CML2

positional arguments:
  nodes                 Number of nodes to generate

optional arguments:
  -h, --help            show this help message and exit
  --ca CAFILE           Use the CA certificate from this file (PEM format), defaults to ca.pem
  -i, --insecure        If no CA provided, do not verify TLS (insecure!)
  -d DISTANCE, --distance DISTANCE
                        Node distance, default 200
  -L LABNAME, --labname LABNAME
                        Lab name to create, default "topogen lab"
  -T TEMPLATE, --template TEMPLATE
                        Configuration template to use, defaults to "iosv"
  --device-template DEV_TEMPLATE
                        CML node definition for routers (e.g. iosv, iol, lxc). Defaults to "iosv"
  --list-templates      List all available templates
  -m {nx,simple,flat}, --mode {nx,simple,flat}
                        mode of operation, default is "simple"
  --flat-group-size FLAT_GROUP_SIZE
                        Routers per unmanaged switch when using flat mode, default 20
  --loopback-255        Use 10.255.C.D/32 for Loopback0 addressing in flat mode (default is 10.20.C.D/32)
  --gi0-zero            Use 10.0.C.D/16 for Gi0/0 addressing in flat mode (default is 10.10.C.D/16)
  --allow-oversubscribe Bypass the recommended 520-node lab limit (use with caution)
  --yaml FILE           Export the created lab to a YAML file at FILE (via controller API)
  --offline-yaml FILE   Generate a CML-compatible YAML locally (no controller required)
  --cml-version ...     CML lab schema version for offline YAML (CML 2.9 uses 0.3.0)

configuration:
  -c CONFIGFILE, --config CONFIGFILE
                        Use the configuration from this file, defaults to config.toml
  -w, --write           Write the default configuration to a file and exit
  -v, --version         show program's version number and exit
  -l LOGLEVEL, --loglevel LOGLEVEL
                        DEBUG, INFO, WARN, ERROR, CRITICAL, defaults to WARN
  -p, --progress        show a progress bar
$
```

At a minimum, the amount of nodes to be created must be provided.

#### Modes

There are three modes available right now:

- `nx`: this creates a partially meshed topology.  It also places nodes in clusters
  which is more pronounced with many nodes (>40).
- `simple` (which is the default): this creates a single string of nodes, laid out
  in a square / spiral pattern.
- `flat`: builds a flat L2 fabric for large-scale experiments. One core unmanaged
  switch (SWmgt0) connects to N access unmanaged switches (SWmgt1..N). Each router
  connects only to its access switch on `Gi0/0`. Group size per access switch is
  controlled by `--flat-group-size` (default 20). No router-to-router links are
  created in this mode.
- `flat-pair`: similar to `flat`, but routers are odd/even paired.
  - Odd routers: `Gi0/0` connects to the access switch and `Gi0/1` connects to the even router's `Gi0/0`.
  - Even routers: no access-switch link; only paired to the preceding odd router.
  - If the last router is odd and has no partner, its `Gi0/1` is unused.

> [!NOTE]
> Flat mode implements a star fabric (not chained). Unmanaged switch interfaces are
> labeled `portN` in generated offline YAML (CML UI may present differently).

#### Templates

To list the available templates, use the `--list-templates` switch.  Templates include:

- `iosv`: default IOSv OSPF-based template
- `iosv-eigrp`: IOSv template that configures EIGRP 100 and advertises both `Gi0/0`
  and `Loopback0` (with `Loopback0` set to passive)
- `iosv-eigrp-stub`: IOSv template that configures EIGRP 100 and advertises both `Gi0/0`
  and `Loopback0` (with `Loopback0` set to passive) and enables eigrp stub connected summary
- `iosv-eigrp-nonflat`: IOSv template for simple/NX modes. EIGRP 100 with passive-interface Loopback0; advertises 10.0.0.0/8 (Lo0) and 172.16.0.0/12 (p2p links).
- `csr-eigrp`: CSR1000v (IOS-XE) template for flat/flat-pair modes. Uses `vrf definition TENANT` and CSR interface labels (`GigabitEthernet1/2/...`).

To choose a specific template, provide the `--template=iosv` switch.

[!NOTE] In non-flat (simple/NX) EIGRP labs, the DNS/jumphost does not run EIGRP, so a default route (0/0) is not automatically originated into the EIGRP domain. Until this is improved, manually originate a default on the intended exit router, or configure a per-router static default toward the DNS path. This does not affect flat/offline mode.

Currently, all router nodes are using the same configuration template. The CML node
definition can be selected independently via `--device-template`.

### Flat mode addressing (deterministic)

In `flat` mode, interface addresses are deterministic and encode the router number
in the last 16 bits (1-based). For router `Rn` where `n` is 1..N:

- `Gi0/0` = `10.10.C.D/16`
- `Loopback0` = `10.20.C.D/32`

Where `C = floor(n / 256)` and `D = n % 256`.

Examples:

- `R1`   → `Gi0/0 10.10.0.1/16`, `Lo0 10.20.0.1/32`
- `R256` → `Gi0/0 10.10.1.0/16`, `Lo0 10.20.1.0/32`
- `R257` → `Gi0/0 10.10.1.1/16`, `Lo0 10.20.1.1/32`

### Scaling limits and assumptions (flat mode)

Flat mode builds a star fabric (not chained). Practical port limits apply:

- Access switch: `group_size + 1` ports (routers + 1 uplink to core) should be ≤ ~32
- Core switch: `ceil(nodes / group_size)` uplinks should be ≤ ~32

Defaults are safe for large labs (e.g., 300 nodes with `--flat-group-size 20` → 21 ports/access, 15 on core).

Assumptions and caveats:

- The guardrails assume the `unmanaged_switch` node definition has roughly 32 usable ports.
- Custom node definitions/images (including customized unmanaged switch or different router images) may change interface counts, labels, or slot allocation. The guardrails do not auto-detect such customizations.
- In generated offline YAML, unmanaged switch interfaces are labeled `portN`; the CML UI may present different labels.

Licensing guidance:

- Typical base licenses allow ~20 nodes. Enterprise tiers often allow up to 520 nodes total.
- A soft cap of 520 nodes is enforced by default; use `--allow-oversubscribe` to bypass if your environment supports more.

Version-specific capacity:

- CML 2.9+ (lab schema `0.3.0`): empirically supports flat labs up to ~500 nodes.
- CML versions prior to 2.9: practical enterprise limit ~300 nodes for this flat EIGRP scenario.
- For offline YAML intended for 2.9+, use `--cml-version 0.3.0`.

Recommended group sizes (stay within 32-port limits):

- 300 nodes: `--flat-group-size 20` → 15 access switches; core ports 15
- 500 nodes (CML 2.9+):
  - `--flat-group-size 20` → 25 access; core ports 25 (safe)
  - `--flat-group-size 25` → 20 access; core ports 20 (safe)
  - `--flat-group-size 30` → 17 access; core ports 17 (safe; access uses 31 ports incl. uplink)

### YAML export (controller)

When `--yaml FILE` is provided, the created lab is exported to the given file after
generation via the controller API. The connected controller must support lab export
via the PCL; otherwise the tool will log an error.

### Offline YAML export (no controller)

Use `--offline-yaml FILE` to emit a CML-compatible YAML locally without contacting
the controller. This is ideal for very large labs and for environments where API
export is not available.

TopoGen does not pick an output filename automatically; you must provide one. We recommend `out/` for generated artifacts.

- Schema selection: `--cml-version` chooses the lab schema version (CML 2.9 uses `0.3.0`).
- Topology: star fabric with one core `SWmgt0`, N access `SWmgt1..N`, and routers `R1..R${nodes}`.
- Configs: rendered from the chosen template (e.g. `iosv-eigrp`).
- Import: In CML, go to Tools → Import/Export → Import Lab and select the YAML.

### VRF support (flat-pair)

In `flat-pair` mode, an optional VRF can be applied to the odd router pair-link interface (`Gi0/1`).

- `--vrf`: enable VRF configuration
- `--pair-vrf NAME`: VRF name to use (default: `tenant`)

When enabled, the generated router configs include a `ip vrf NAME` stanza and apply `ip vrf forwarding NAME` under `Gi0/1` on odd routers.

### Examples

Create a 300-node flat star lab directly on a controller (insecure TLS):

```powershell
$env:VIRL2_URL="https://controller/"; $env:VIRL2_USER="user"; $env:VIRL2_PASS="pass"
topogen -L "FlatLab-300-star" -T iosv -m flat --flat-group-size 20 --insecure --progress 300
```
Create a 20-node simple lab with EIGRP (non-flat):

powershell
topogen -L "Simple-20-eigrp" -T iosv-eigrp-nonflat --device-template iosv `
  -m simple --distance 250 --insecure --progress 20
Create a 20-node NX lab with EIGRP (non-flat):

powershell
topogen -L "NX-20-eigrp" -T iosv-eigrp-nonflat --device-template iosv `
  -m nx --distance 250 --insecure --progress 20
Create and export a 500-node NX lab with EIGRP (YAML filename is Git-ignored):

powershell
topogen -L "NX-500-eigrp" -T iosv-eigrp-nonflat --device-template iosv `
  -m nx --distance 300 --yaml NX-500-eigrp.yaml --insecure --progress 500


Create the same lab with EIGRP config and export YAML:

```powershell
$env:VIRL2_URL="https://controller/"; $env:VIRL2_USER="user"; $env:VIRL2_PASS="pass"
topogen -L "FlatLab-300-star-eigrp" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --yaml "flatlab-300-star-eigrp.yaml" --insecure 300
```

Create a 10-node offline YAML (no controller):

```powershell
topogen --cml-version 0.3.0 -L "TestOffline-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --offline-yaml out/test-offline-10.yaml 10
```

Create a 12-node `flat-pair` offline YAML with VRF enabled on odd routers (`Gi0/1`):

```powershell
topogen --cml-version 0.3.0 -L "vasailli" -T iosv --device-template iosv -m flat-pair \
  --flat-group-size 20 --vrf --pair-vrf TENANT --offline-yaml out/vasailli-12-flat-pair.yaml 12
```

Create a 40-node `flat-pair` offline YAML using CSR1000v (IOS-XE) and VRF EIGRP:

```powershell
topogen --cml-version 0.3.0 -L "IOSXE-VRF-EIGRP-40" -T csr-eigrp --device-template csr1000v -m flat-pair \
  --flat-group-size 20 --vrf --pair-vrf TENANT --offline-yaml out/iosxe-vrf-eigrp-40.yaml 40
```

Create a 300-node offline YAML:

```powershell
topogen --cml-version 0.3.0 -L "FlatLab-300-star-eigrp-l32" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --offline-yaml out/flatlab-300-star-eigrp-l32.yaml 300
```

Create a 500-node offline YAML:

```powershell
topogen --cml-version 0.3.0 -L "FlatLab-500-star-eigrp-l32" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --offline-yaml out/flatlab-500-star-eigrp-l32.yaml 500
```

Addressing variant examples (flat mode):

- Use Lo0 in 10.255.C.D/32 and Gi0/0 in 10.0.C.D/16 (offline YAML):

```powershell
topogen --cml-version 0.3.0 -L "FlatLab-300-addr-variant" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --loopback-255 --gi0-zero --offline-yaml out/flatlab-300-addr-variant.yaml 300
```

- Same addressing variant on controller (online):

```powershell
topogen -L "FlatLab-300-addr-variant" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --loopback-255 --gi0-zero --insecure 300
```

> Note: Generated offline YAML artifacts are recommended to be written under `out/` and are ignored by Git.

#### Other Configuration

IP address ranges are configured via a configuration file, if present.  The
defaults are like shown here:

```toml
loopbacks = "10.0.0.0/8"
p2pnets = "172.16.0.0/12"
nameserver = "8.8.8.8"
domainname = "virl.lab"
username = "cisco"
password = "cisco"
```

The username and password are used for the device configurations (e.g. the
Alpine DNS node and the generated routers).  The nameserver value is not used
at the moment (it is actually replaced with the IP address of the DNS host's
second interface / NIC facing the router network).

## Operation

> [!NOTE]
> For large online builds (e.g., simple/NX with hundreds of nodes), the CML UI may not
> visibly update the topology immediately. It is normal for no changes to appear until
> roughly 25% of the creation process has completed. Let TopoGen continue; nodes and
> links will show up progressively as creation advances.

The topology has an external connector and a DNS-host (based on Alpine).  On
that host, a dnsmasq DNS server is running which can resolve all IP addresses
of all topology router loopbacks.  All topology routers are also using this
DNS server (assuming they have connectivity to it).

> [!NOTE]
>
> Since the Alpine node does not include dnsmasq by default, it
> will pull in and install this package from the Internet. Therefore it
> is required to have Internet connectivity for this to work! Once the
> network has been created and full connectivity is established, it
> should be possible to SSH/Telnet to all nodes using their node names.
> The below shows logging into the Jumphost (at 192.168.255.100) via
> the controller (at 192.168.122.245) and then onward to router `r1`
> using its name.

```plain
rschmied@delle:~/Projects/topogen$ ssh -tp1122 sysuser@192.168.122.245 ssh cisco@192.168.255.100
cisco@192.168.255.100's password: 
Welcome to Alpine!

The Alpine Wiki contains a large amount of how-to guides and general
information about administrating Alpine systems.
See <http://wiki.alpinelinux.org/>.

You can setup the system with the command: setup-alpine

You may change this message by editing /etc/motd.

dns-host:~$ telnet r1
Connected to r1

Entering character mode
Escape character is '^]'.


**************************************************************************
* IOSv is strictly limited to use for evaluation, demonstration and IOS  *
* education. IOSv is provided as-is and is not supported by Cisco's      *
* Technical Advisory Center. Any use or disclosure, in whole or in part, *
* of the IOSv Software or Documentation to any third party for any       *
* purposes is expressly prohibited except as otherwise authorized by     *
* Cisco in writing.                                                      *
**************************************************************************

User Access Verification

Username: cisco
Password: 
**************************************************************************
* IOSv is strictly limited to use for evaluation, demonstration and IOS  *
* education. IOSv is provided as-is and is not supported by Cisco's      *
* Technical Advisory Center. Any use or disclosure, in whole or in part, *
* of the IOSv Software or Documentation to any third party for any       *
* purposes is expressly prohibited except as otherwise authorized by     *
* Cisco in writing.                                                      *
**************************************************************************
R1#traceroute 192.168.122.1
Type escape sequence to abort.
Tracing the route to 192.168.122.1
VRF info: (vrf in name/id, vrf out name/id)
  1 from-r1-gi0-0-to-r9-gi0-0.virl.lab (172.16.0.2) 3 msec
    from-r1-gi0-1-to-r2-gi0-0.virl.lab (172.16.0.6) 9 msec
    from-r1-gi0-2-to-r4-gi0-0.virl.lab (172.16.0.10) 4 msec
  2 from-r7-gi0-4-to-r9-gi0-2.virl.lab (172.16.0.57) 10 msec
    from-r2-gi0-3-to-r7-gi0-0.virl.lab (172.16.0.22) 18 msec
    from-r4-gi0-2-to-r7-gi0-2.virl.lab (172.16.0.38) 14 msec
  3 172.16.0.77 7 msec 10 msec 11 msec
  4 192.168.255.1 11 msec 14 msec 9 msec
  5 192.168.122.1 13 msec 12 msec 11 msec
R1#
```
