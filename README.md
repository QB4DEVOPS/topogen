<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.9.0
Date Modified: 2026-09-21

- Called by: Users (primary entry point), package managers (PyPI), GitHub viewers
- Reads from: None (documentation only)
- Writes to: None (documentation only)
- Calls into: docs/USER-GUIDE.md, DEVELOPER.md, PKI.md, CHANGES.md

Purpose: Get TopoGen installed and produce a first CML lab. Full usage lives in
         docs/USER-GUIDE.md. Current flags: `topogen --help`.

Blast Radius: None (documentation only, does not affect code execution)
-->

# TopoGen for CML2

TopoGen generates [Cisco Modeling Labs](https://developer.cisco.com/modeling-labs) topologies and day-0 device configs from the CLI. Write a lab YAML on disk, then import it into CML when you are ready.

It numbers links and loopbacks, renders IOS/IOS-XE configs, and can emit Ansible and Terraform artifacts so the lab is ready for the next step.

![Demo](.images/demo.gif)

## Install

Python 3.12+. Clone this repo, then pick one:

**pip**

```shell
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .
```

**uv**

```shell
uv venv
uv sync --frozen
# optional: source .venv/bin/activate
```

Check it:

```shell
topogen -v
```

That should print `0.3.0` (or whatever is in `pyproject.toml`). If it prints an older version, reinstall with `python -m pip install -e .`.

You can also run `python -m topogen` or `uv run topogen` if the venv is not activated.

The CML Python client (PCL) must match your controller. If online mode fails, install the wheel from your controller at `/client`. For `--mode nx`, also install SciPy/NumPy: `uv sync --all-extras --dev --frozen`.

## First lab

No controller required. This writes a 4-router simple (chain) lab:

```shell
topogen 4 -m simple -L first-lab --offline-yaml out/first-lab.yaml --overwrite
```

You should get `out/first-lab.yaml`. In CML: **Tools → Import/Export → Import Lab**, and select that file.

To import and start from the CLI (controller already reachable):

```shell
export VIRL2_URL="https://cml-controller.example/"
export VIRL2_USER="user"
export VIRL2_PASS="pass"
topogen --up out/first-lab.yaml -i
```

PowerShell:

```powershell
$env:VIRL2_URL = "https://cml-controller.example/"
$env:VIRL2_USER = "user"
$env:VIRL2_PASS = "pass"
topogen --up out/first-lab.yaml -i
```

`-i` skips TLS verify (lab-only). `--up` is `--import-yaml` + `--import` + `--start`; the lab starts in the background.

### Optional GUI

```shell
python -m pip install -e ".[gui]"
topogen-gui
```

Set `offline-yaml` to `out/my-lab.yaml`, pick mode / template / nodes, click Start, then import the YAML in CML.

## Next labs

```shell
# 10-node flat L2 fabric with EIGRP
topogen 10 -m flat -T iosv-eigrp --offline-yaml out/flat-10.yaml --overwrite

# DMVPN: 1 hub + 3 spokes (without --dmvpn-hubs, nodes is spoke count)
topogen 3 -m dmvpn -T iosv-dmvpn --offline-yaml out/dmvpn-4.yaml --overwrite
```

Current flags: `topogen --help`. Worked examples, NaC, OOB, PKI, and CML schema notes: [docs/USER-GUIDE.md](docs/USER-GUIDE.md).

Device username/password and IP pools default from `config.toml` (copy [config.sample.toml](config.sample.toml) or pass `-c`).

## Docs

| I want… | Go here |
|---------|---------|
| Install and first lab | this README |
| Modes, examples, NaC, OOB, CML import | [docs/USER-GUIDE.md](docs/USER-GUIDE.md) |
| PKI / certificates | [PKI.md](PKI.md) |
| Develop or contribute | [DEVELOPER.md](DEVELOPER.md), [CONTRIBUTING.md](CONTRIBUTING.md) |
| What changed | [CHANGES.md](CHANGES.md) |
