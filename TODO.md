<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.4.0

- Called by: Developers planning features, LLMs adding work items, project management
- Reads from: Developer input, user requests, issue tracker
- Writes to: None (documentation only, but drives development decisions)
- Calls into: References README.md, CHANGES.md, DEVELOPER.md for completed work

Purpose: Living document tracking current work, future ideas, and issue candidates.
         Organizes feature development roadmap and TODO items for developers and LLMs.

Blast Radius: Medium (guides development priorities but doesn't affect code execution)
              Moving items from "Current work" to "Done" signals feature completion.
-->

# TODO

This file tracks in-progress work and future ideas for TopoGen.

## Conventions

- Offline YAML output files should be written under `out/`.
- `out/` is in `.gitignore`.
- Prefer filename = lab name:
  - Lab name: `IOSXE-DMVPN-FLAT-PAIR-3H-P2-EIGRP-N63`
  - Offline YAML: `out\IOSXE-DMVPN-FLAT-PAIR-3H-P2-EIGRP-N63.yaml`

- TODO buckets (to avoid confusion):
  - `## Current work` = items for the feature currently being worked on.
  - `## Future ideas` = new ideas not being worked on yet.
  - `## Promote to Issues` = issue-worthy items that should become GitHub Issues when running the workflow.

- When asking an LLM to add something, prefer:
  - "Add to Current work: ..." or "Add to Future ideas: ..." or "Promote to Issues: ..."

## Feature roadmap (ordered)

1. ~~OOB management network for flat, flat-pair, and DMVPN modes~~ (completed)
2. DMVPN IPsec protection (IKEv2 + PSK) (completed)
3. DMVPN security roadmap (PKI)
4. Decide/implement least-astonishment semantics for DMVPN `--dmvpn-underlay flat-pair` node counts

## Current work

### ⚠️ DO THIS NEXT!!!! — Blank template for CML AutoNetkit bootstrap testing
- [ ] Create `src/topogen/templates/blank.jinja2` with truly empty config (just `!` or `end`)
- [ ] Test with: `topogen --template blank -m flat --offline-yaml out/bootstrap-test-100.yaml 100`
- [ ] Verify CML AutoNetkit bootstrap works on import (no config = AutoNetkit runs on first boot)
- [ ] Update README.md to document `--template blank` option
- [ ] Update CHANGES.md with new blank template feature
- Why critical: TopoGen should support blank/no-config topology generation for testing CML's AutoNetkit bootstrap at scale
- Use case: Generate 10-100 node topologies with no configs, import to CML, test if AutoNetkit bootstrap function works

### feat/pki-ca — CA-ROOT for flat, flat-pair, and DMVPN modes
- [x] Copy csr-dmvpn.jinja2 → csr-pki-ca.jinja2 as starting point (DONE - template exists)
- [x] Add `--pki` CLI flag (main.py) (DONE)
- [x] Add CA-ROOT to offline_flat_yaml() — connects to SW0 (slot 0) + SWoob0 if --mgmt (DONE)
- [x] Add CA-ROOT to offline_flat_pair_yaml() — connects to SW0 (slot 0) + SWoob0 if --mgmt (DONE)
- [x] Add CA-ROOT to offline_dmvpn_yaml() — connects to SWnbma0 (slot 0) + SWoob0 if --mgmt (DONE)
- [x] Add CA-ROOT to offline_dmvpn_flat_pair_yaml() — connects to SWnbma0 (slot 0) + SWoob0 if --mgmt (DONE)
- [x] CA IP = last usable in appropriate CIDR (.255.254 for data/loopback, broadcast-1 for DMVPN NBMA) (DONE)
- [x] Added --pki to args_bits in all 4 offline functions for lab description tracking (DONE)
- [ ] Validate with offline YAML generation for all 4 modes
- Naming convention: CA-ROOT (this branch), CA-POLICY (.255.253) / CA-SIGN (.255.252) reserved for future multi-CA labs
- Scope: flat/flat-pair/dmvpn/dmvpn-flat-pair offline modes; simple/nx modes deferred

## Promote to Issues

- [ ] (add issue-worthy items here)

- [ ] Usability fix: allow `python -m topogen ...` (no `.main`) by adding `src/topogen/__main__.py`

## Done

See `CHANGES.md` and `README.md` for completed features.

Recent completions:
- [x] Add `--mgmt-bridge` support for online NX and simple modes (see CHANGES.md)
- [x] Add `--start` flag for auto-starting labs after creation (see CHANGES.md)
- [x] Add lab URL printing after creation for easy browser access (see CHANGES.md)
- [x] Include all CLI args in lab description for repeatability (see CHANGES.md)
- [x] Add external-connector bridge support for OOB management (offline modes) (see CHANGES.md)
- [x] OOB management network for flat, flat-pair, and DMVPN modes (see CHANGES.md)

## Future ideas

- [ ] 3-level PKI hierarchy (Root CA + Policy CA + End-entity certificates)
  - Why: Production-grade PKI best practice; teach proper CA hierarchy design
  - Nodes: CA-ROOT (root CA), CA-POLICY (policy/intermediate CA), spokes/hubs (end-entity certs)
  - Certificate profiles for proper constraints and key usage:
    ```
    crypto pki certificate profile CA-ROOT-PROFILE
     subject-name CN=CA-ROOT,O=Lab,C=US
     validity 7300
     basicConstraints ca true
     key-usage keyCertSign cRLSign

    crypto pki trustpoint CA-ROOT
     certificate profile CA-ROOT-PROFILE
    ```
  - Device certificates (spokes/hubs) must include EKU IPsec:
    ```
    crypto pki certificate profile DEVICE-PROFILE
     extended-key-usage ipsec
    ```
  - Naming: CA-ROOT (root), CA-POLICY (policy CA), CA-SIGN (alternate policy CA for future)
  - Blast radius: render.py (create CA-POLICY node), templates (certificate profiles), DMVPN templates (device profiles with EKU)
- [ ] Support IOSv for PKI CA-ROOT (currently CSR1000v only)
  - Why: CA-ROOT is currently hardcoded to csr1000v node definition (see render.py ca_dev_def)
  - Current: csr-pki-ca.jinja2 template uses CSR interface names (GigabitEthernet1, Gi5)
  - Future: Make template adaptable to IOSv (GigabitEthernet0/1, Gi0/5) if PKI server works on IOSv
  - Requires: Pass dev_def to template context, add conditional interface naming in template
  - Blast radius: render.py (CA creation), csr-pki-ca.jinja2 (interface config), offline YAML generation
- [ ] Add `--strong` and `--stronger` flags for production-grade crypto (nice to have, educational)
  - Why: Teach encryption best practices - demonstrate difference between lab crypto and production crypto
  - Tiered approach: default (lab) → strong (compatible hardening) → stronger (maximum security, requires ECC)
  - PKI changes:
    - Default (no flag): RSA 2048-bit keys, 10-year CA cert, 3-year device certs (quick, "just get it running")
    - `--strong`: RSA 4096-bit keys, 2-year CA cert, 1-year device certs (production-grade, compatible)
    - `--stronger`: ECDSA P-256 or P-384 keys (ECC certificates), 2-year CA cert, 1-year device certs (maximum security, requires ECC support)
  - IPsec changes (when `--dmvpn-security ikev2-psk` is used):
    - Default: IKEv2 DH group 14 (2048-bit MODP), SHA-1, AES-128, PFS group 14
    - `--strong`: IKEv2 DH group 15/16 (3072/4096-bit MODP, no ECC required), SHA-256, AES-256, PFS group 15/16, PRF SHA-256 (compatible with all devices)
    - `--stronger`: IKEv2 DH group 19/20 (256/384-bit ECC), SHA-384, AES-256-GCM, PFS group 19/20, PRF SHA-384 (requires ECC support)
  - Affects: PKI server config (csr-pki-ca.jinja2), spoke/hub crypto config (dmvpn templates), IKEv2 policy/proposal/profile
  - Implementation: Add flags to main.py, pass `strong_crypto` and `stronger_crypto` to template context, conditional crypto settings in templates
  - Educational value: Students learn "here's lab mode vs production hardening vs maximum hardening" across PKI AND IPsec
  - Compatibility: `--strong` works on all IOS/IOS-XE, `--stronger` requires ECC-capable devices (documented limitation)
  - Blast radius: main.py (argparse), render.py (context), PKI templates (conditional crypto config), DMVPN templates (IKEv2 policy)
- [ ] Add NAT mode support for external-connector (in addition to current System Bridge mode)
  - Why: Enable outbound-only connectivity for OOB management networks where devices need to reach external resources but don't need to be reachable from outside
  - Current implementation uses "System Bridge" mode (bidirectional connectivity)
  - NAT mode would be useful for security-focused deployments where management plane should only initiate outbound connections
- [ ] Refactor: deduplicate offline YAML emission for `--mgmt-bridge` (external_connector + SWoob0 port offset + links)
  - Today this logic is repeated across multiple offline renderers in `src/topogen/render.py`
  - Goal: centralize into a shared helper to reduce risk of fixing one mode and missing others
- [ ] Invisible metadata embedding via 1pt transparent annotation (low-medium effort, 2-3pt)
  - Why: Enable round-trip regeneration (`topogen regenerate lab.yaml` / `topogen --up lab.yaml`) with zero visual footprint
  - Contract: TopoGen stores regeneration intent in a CML Text Annotation named TOPOGEN_INTENT. Round-trip metadata must live in a first-class object that the platform itself owns.
  - Approach: Embed base64-encoded JSON intent in a 1pt font, fully transparent annotation positioned off-canvas (-200, -200)
  - Survives: All CML round-trips (export → download → share → import → re-export) — annotations are native CML 2.5+ feature
  - Zero user impact: Literally invisible (1pt + transparent background/border + off-canvas position)
  - Intent schema: `TOPOGEN-INTENT-v1:{base64(json({mode, nodes, template, flags, ...}))}` — version prefix allows future schema evolution
  - Implementation:
    - Add annotation injection to all 4 offline renderers (`offline_flat_yaml`, `offline_flat_pair_yaml`, `offline_dmvpn_yaml`, `offline_dmvpn_flat_pair_yaml`)
    - Create parser function to extract/decode intent from annotations in imported YAML
    - Add `topogen regenerate <file.yaml>` command to reconstruct args from embedded intent
    - Optional: `--embed-metadata` (default on), `--visible-metadata-badge` (branding), `--hide-metadata` (strip on output)
  - Level of effort: 4-6 hours (2-3 hours annotation injection + 1 hour parser + 1-2 hours testing + 30 min docs)
  - Depends on: `--import` / `--up` flags for import workflow (see other future idea)
  - Blast radius: render.py (4 offline functions + parser), main.py (regenerate command), no breaking changes
  - Compared to alternatives:
    - vs lab.description: Invisible (not visible in UI properties panel)
    - vs metadata node: No canvas clutter (no extra router/device)
    - vs external file: Survives round-trips (stays with the YAML)
  - Workflow unlocked:
    ```bash
    # Generate offline (no controller)
    topogen -m flat-pair -T iosv-eigrp --offline-yaml out/lab.yaml --mgmt --pki 50
    # Share lab.yaml with colleague
    # Colleague imports, tweaks in CML, exports as lab-v2.yaml
    # Regenerate exact topology from exported YAML
    topogen regenerate lab-v2.yaml --offline-yaml out/lab-v3.yaml
    # Or deploy directly to CML
    topogen --up lab-v2.yaml
    ```
- [ ] (add ideas here)
- [ ] Optional: interactive dependency graph / call graph visualization
  - Goal: visualize code relationships (imports/calls) as a movable graph (nodes/edges)
  - Possible outputs: Mermaid graph in Markdown, Graphviz DOT/SVG, or JSON for a web viewer
  - Scope: at least `main.py` -> `render.py` -> `templates/*` plus other core modules
- [ ] Named EIGRP support (feature)
  - Standardize templates to support a named EIGRP config model intentionally (not incidentally)
  - Decide how this interacts with VRF (GRT + VRF address-families) and split-horizon controls

- [ ] Named OSPF support (feature)
  - Add an intentional named OSPF config model (VRF + GRT where applicable)

- [ ] Add CLI to select routing protocol configuration model (named EIGRP / named OSPF vs classic/numeric)
  - Why: avoid mixed-mode confusion; make the chosen model explicit

- [ ] DMVPN Phase 3 support
  - NHRP redirect on hubs
  - NHRP shortcut on spokes
  - EIGRP next-hop / split-horizon handling for Phase 3

- [ ] Validate runtime behavior in CML for DMVPN underlay `flat-pair`
  - odd routers are DMVPN endpoints (Tunnel0/NHRP)
  - even routers are EIGRP-only
  - odd router NBMA interface is passive for EIGRP (no neighbors on Gi0/0)

- [ ] Decide/implement least-astonishment semantics for DMVPN `--dmvpn-underlay flat-pair` node counts
  - whether `N` should mean total routers vs DMVPN endpoints
  - or document the doubling behavior clearly

- [ ] DMVPN security roadmap
  - IKEv2 with PSK
  - PKI support

- [ ] Front Door VRF (FVRF) for DMVPN

- [ ] Explore shareable, self-describing lab intents (example lab collection / “marketplace” concept)
- [ ] Formalize serialized intent model (versioned `topogen:` schema embedded in lab YAML)
- [ ] Support regenerating a lab from its embedded intent (`topogen regenerate lab.yaml`)
- [ ] Make management plane a first-class intent (mgmt VRF, reserved interface, IPv4/IPv6 mode)
- [ ] Emit machine-readable inventory alongside offline lab output
- [ ] Add intent-level validation and least-astonishment checks before rendering
- [ ] Support named intent profiles / presets for common lab patterns
- [ ] Curate example offline labs using embedded intent (shareable / regeneratable lab collection)
- [ ] Serialized Intent & Round-Trip Capability:
  - Embed all generation parameters (topology mode, node count, addressing model) directly into the lab YAML under a `topogen:` metadata block.
  - Implement a `topogen regenerate <file.yaml>` command that reads this metadata to deterministically recreate or update the lab.
- [ ] Intent-based lab generation (medium effort)
  - Why: Unlock full round-trip editing and GitOps workflows by making intent the source of truth.

- [ ] Management Plane as First-Class Citizen:
  - Automate a dedicated `management-vrf` configuration for `GigabitEthernet0/0` across all routers.
  - Implement a deterministic IP calculator to assign static IPv4 and IPv6 management addresses based on Node ID.

- [ ] Automation Inventory Emission:
  - Generate an `inventory.json` (or `.yaml`/`.csv`) artifact during the offline generation phase.
  - Include node names, management IPs, VRF names, and platform types to enable instant tool ingestion (Ansible, Nornir, Netmiko).

- [ ] Offline Validation Sidecar:
  - Emit a standalone `verify_connectivity.py` script alongside the lab YAML.
  - Use the generated inventory to automatically test SSH reachability and protocol health (e.g., DMVPN status, OSPF neighbors) post-boot.

- [ ] Gooey Round-Trip Integration:
  - Add logic to prepopulate Gooey GUI fields by parsing the serialized intent from an existing lab YAML.

- [ ] Add dedicated management VRF on Gi0/0 with deterministic IPv4/IPv6 addressing (medium effort).
  - Why: Enables isolated mgmt plane for hundreds of routers; deterministic IPs (e.g., 172.16.0.{n+10}/24) make it predictable and unlock programmatic config via tools like Ansible; tie to --enable-mgmt-vrf flag and wire to a mgmt_switch.

- [ ] Embed serialized intent in YAML (`topogen:` block) for regeneration workflows (medium effort).
  - Why: Makes YAML the single source of truth with embedded params (mode, nodes, template, mgmt config); add `topogen regenerate lab.yaml` subcommand to unlock round-trip editing, GitOps, and easy tweaks without re-running full CLI.

- [ ] Full DHCP + IPv6 on management plane (medium effort).
  - Why: Layer DHCPv4/v6 via dnsmasq on DNS host with conditional templates for static vs. dynamic; pairs with mgmt VRF for "instant" auto-setup and dual-stack support in large labs.

- [ ] Post-build automation hooks (low effort).
  - Why: Add --post-hook flag for running scripts after generation (e.g., start lab, poll readiness, or run Ansible from inventory); unlocks "one command to fully configured lab" workflows.

- [ ] Test unmanaged switches in all modes (flat, flat-pair, etc.) for port limits at 300+ nodes (medium effort).
  - Why: Verify no overflows and add warnings/guardrails; builds confidence for huge-scale labs and document results in README for better user guidance.

- [ ] Prepopulate Gooey GUI from existing YAML metadata (low effort).
  - Why: Add "Load from YAML" file chooser to parse `topogen:` block and auto-fill fields; unlocks quick interactive edits/tweaks in GUI without retyping params.

- [ ] Update README with topology diagrams and scale examples (low effort).
  - Why: Add visuals for flat star vs. pair topologies and command examples (e.g., 300-node flat lab); makes the project more approachable and helps users understand scale capabilities.

- [ ] Rework README `--help` output block to prevent CLI drift (low effort).
  - Why: The embedded `topogen --help` block in README can silently drift from `main.py` as new flags are added (e.g., `--pki`, `--mgmt`).
  - Options: (a) Auto-generate from `topogen --help` during release, (b) Replace with "run `topogen --help` for current flags" and link to DEVELOPER.md for flag details, (c) Add a CI check that diffs README help block against actual CLI output.
  - Blast radius: README.md only (documentation, no code changes).

- [ ] Add machine-parsable artifact summary line after offline YAML generation (low effort).
  - Why: Enables CI/CD pipelines and wrapper scripts to grep a single structured line for path, size, mode, and node count.
  - Format: `ARTIFACT_YAML=out/lab.yaml bytes=862312 kind=flat-pair nodes=520`
  - When: Implement when a CI/CD pipeline or automation script needs to consume the output programmatically.
  - Blast radius: render.py (4 offline write paths), no behavior change to existing log lines.

- [ ] Add `--quiet` flag to suppress non-essential output (low effort).
  - Why: When running in scripts or CI/CD, users may only want errors or the final artifact path, not progress/config warnings.
  - Behavior: Suppress INFO and WARNING logs, only show ERROR and the final output line.
  - Pairs well with: Machine-parsable artifact summary (above) for clean scripted workflows.
  - Blast radius: main.py (argparse + log level config), no changes to render logic.

- [ ] Add `--import` and `--import-yaml` flags for offline-to-CML workflow (medium effort).
  - Why: Currently there's no way to take an offline YAML and push it into CML without switching to online mode.
    This bridges the gap: generate offline → inspect/edit → import → start.
  - New flags:
    - `--import-yaml <file>`: Read an existing offline YAML (skip generation)
    - `--import`: Import the generated/read YAML into CML via `virl2_client`
    - `--import-and-start`: Sugar for `--import --start` (composable)
  - Existing flag: `--start` stays as-is (matches CML API `lab.start()` vocabulary)
  - Composable examples:
    - Generate + import + start: `topogen ... --offline-yaml out/lab.yaml --import --start`
    - Read existing + import: `topogen --import-yaml out/lab.yaml --import`
    - Read + import + start: `topogen --import-yaml out/lab.yaml --import-and-start`
  - Output: Print lab URL after import (e.g., `https://controller/lab/abc123`) for easy browser access, same as online mode.
  - Blast radius: main.py (argparse dispatch), render.py (import path via virl2_client), no changes to offline generation.

- [ ] Add `--up <file>` shorthand and `--print-up-cmd` flag (low effort, sugar).
  - Why: `--up` is sugar for `--import-yaml <file> --import --start` in a single flag.
    Enables a clean two-step workflow: generate offline, then deploy when ready.
  - `--print-up-cmd`: When used with `--offline-yaml`, prints the exact `topogen --up <file>` command
    to run later. Only takes effect when `--up` is not already used on this run.
  - Example workflow:
    ```
    # Step 1: Generate (no controller needed)
    topogen ... --offline-yaml out/lab.yaml --print-up-cmd
    # Output: "When you're ready: topogen --up out/lab.yaml"

    # Step 2: Deploy (when ready)
    topogen --up out/lab.yaml
    ```
  - Depends on: `--import` and `--import-yaml` flags (above).
  - Blast radius: main.py (argparse alias), no new logic beyond existing import+start.

- [ ] Trim and reorganize README.md for readability (low effort).
  - Why: README has grown large with inline help output, detailed examples, and mixed audiences (end-users vs contributors). Makes it harder to scan and find what you need.
  - Options: (a) Move contributor/developer content to DEVELOPER.md, (b) Collapse verbose sections behind summary headings, (c) Replace inline `--help` block with a link (pairs with the help-drift item above).
  - Blast radius: README.md only (documentation, no code changes).
