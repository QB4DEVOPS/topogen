<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.5.2

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

### feat/pki-ca — Single root CA router for DMVPN PKI
**Note: PKI is currently broken.** Do not rely on it until fixed.
- [x] Copy csr-dmvpn.jinja2 → csr-pki-ca.jinja2 as starting point
- [x] Add `--pki` and `--pki-enroll scep|cli` CLI flags (main.py)
- [x] Add CA-ROOT router to render_dmvpn_network() — connects to SWnbma0 (slot 0) + OOB switch if --mgmt
- [x] CA IP = last usable in NBMA CIDR (no conflict with sequential router allocation)
- [ ] Validate with offline YAML
- Naming convention: CA-ROOT (this branch), CA-POLICY / CA-SIGN reserved for future multi-CA labs

### EEM scripts (PKI) — working status

Script bodies live in `examples/`. Check off when confirmed working on device.

| Script name | Example file | Working |
|-------------|--------------|---------|
| CA-ROOT-SET-CLOCK | `examples/eem-ca-root-set-clock.txt` | [x] |
| CLIENT-PKI-SET-CLOCK | `examples/eem-client-pki-set-clock.txt` | [x] |
| CLIENT-PKI-AUTHENTICATE | `examples/eem-client-pki-authenticate.txt` | [ ] |
| CLIENT-PKI-CHAIN | `examples/eem-client-pki-chain.txt` | [ ] |
| AUTO-AUTH | `examples/eem-auto-auth.txt` | [ ] |
| CLIENT-PKI-ENROLL | `examples/eem-client-pki-enroll.txt` | [ ] |
| do-ssh | `examples/eem-do-ssh.txt` | [ ] |

## Promote to Issues

- [ ] (add issue-worthy items here)

- [ ] **Fix CA-ROOT boot: EEM "end" action outside conditional block.** Observed: `%HA_EM-6-FMPD_EEM_CONFIG: CA-ROOT-SET-CLOCK: "end" action found outside of conditional block`. EEM applet CA-ROOT-SET-CLOCK (and client CLIENT-PKI-SET-CLOCK) use `action X.Y end` to close if blocks; on some IOS-XE versions the parser reports "end" outside conditional. Fix: ensure `end` actions are indented so the parser associates them with the correct if block (e.g. ` action 1.10 end` → `  action 1.10 end` for CA-ROOT; client has ` action 1.99 end`). See render.py `_pki_ca_clock_eem_lines()` and `_pki_client_clock_eem_lines()`.

- [ ] **Fix CA-ROOT boot: CVAC rejects `ip http secure-server trustpoint CA-ROOT-SELF`.** Observed: `%CVAC-4-CLI_FAILURE: Configuration command failure: 'ip http secure-server trustpoint CA-ROOT-SELF' was rejected` (twice). Consequence: "Failed to generate persistent self-signed certificate. Secure server will use temporary self-signed certificate." Cause: config is applied in order; the trustpoint CA-ROOT-SELF does not exist yet when `ip http secure-server trustpoint CA-ROOT-SELF` is applied. Fix: reorder so `crypto key generate rsa ... CA-ROOT-SELF` and `crypto pki trustpoint CA-ROOT-SELF` (and subcommands) appear before `ip http secure-server` and `ip http secure-server trustpoint CA-ROOT-SELF` in all CA and client PKI blocks. Remove duplicate `ip http secure-server` / `ip http secure-server trustpoint` from inline pki_config_lines in render.py (they should only come from _pki_ca_self_enroll_block_lines / client block after trustpoint is defined).

- [ ] Online lab creation: show lab definition size (X.X KB) when upload succeeds
  - Current: render_flat_network() calls export_lab() after "Flat management network created"; if content is None we log "Lab created - uploaded to controller" (no size). When export_lab returns data we log "Lab created (%.1f KB) - uploaded to controller".
  - Observed: online flat run showed "Lab created - uploaded to controller" (no size), so export_lab returned None or failed. Investigate virl2_client export_lab behavior so size is shown for online create (same UX as offline YAML file size).

- [ ] **Fix next:** CA-ROOT time EEM (CA-ROOT-SET-CLOCK) missing when lab is created online. Offline flat/DMVPN/flat-pair inject _pki_ca_clock_eem_lines() into CA config; online flat builds CA from csr-pki-ca.jinja2 only (no EEM). User expects PKI/clock behavior to work the same whether lab is created offline or online. Add CA clock EEM to online flat CA build in render_flat_network() (e.g. append _pki_ca_clock_eem_lines() before assigning ca_router.configuration).

## Done

See `CHANGES.md` and `README.md` for completed features.

Recent completions:
- [x] Offline-to-CML import: `--import-yaml`, `--import`, `--up`, `--print-up-cmd`, non-blocking `--start` (see CHANGES.md)
- [x] Allow `python -m topogen` via `src/topogen/__main__.py` (see CHANGES.md)
- [x] Add `--mgmt-bridge` support for online NX and simple modes (see CHANGES.md)
- [x] Add `--start` flag for auto-starting labs after creation (see CHANGES.md)
- [x] Add lab URL printing after creation for easy browser access (see CHANGES.md)
- [x] Include all CLI args in lab description for repeatability (see CHANGES.md)
- [x] Add external-connector bridge support for OOB management (offline modes) (see CHANGES.md)
- [x] OOB management network for flat, flat-pair, and DMVPN modes (see CHANGES.md)

## Future ideas

- [ ] Add `--clock-set` to opt-in to `do clock set` in PKI configs; default to not using `do` command for time
  - Why: Today PKI injects `do clock set ...` so the clock is authoritative and PKI comes up quickly. Some users prefer NTP or external automation to set time and do not want TopoGen to inject clock-set.
  - Behavior: When `--clock-set` is set, keep current behavior (inject `do clock set` in CA and client PKI blocks). When omitted, do not inject clock-set; time is left to NTP or other automation.
  - Note: At this point, getting PKI and clients stable without injected clock may require other automation (e.g. Ansible, EEM, or out-of-band time sync) to take over. TopoGen would then focus on topology and base PKI config; clock and post-boot auth/save would be handled elsewhere.
  - Blast radius: main.py (argparse), render.py (_pki_ca_self_enroll_block_lines, _inject_pki_client_trustpoint, _pki_ca_clock_eem_lines, _pki_client_clock_eem_lines — gate clock-set on flag), README.
- [ ] Replace `--pki-enroll scep|cli` with `--pki-scep` boolean flag (refactor + feature)
  - `--pki-enroll` is defined in main.py but never read in render.py — it is dead code
  - New design: `--pki` = CA-ROOT node in lab (no change to router configs); `--pki-scep` = non-CA routers get trustpoint + SCEP enrollment pointing at CA-ROOT
  - Dependency: `--pki-scep` requires `--pki` (enforce in main.py)
  - CA IP (`ca_g_addr.ip`) is already computed; pass it to router Jinja context as SCEP enrollment URL
  - Also fix CA name inconsistency: DMVPN render path uses `ROOT-CA`; flat-pair render paths use `CA-ROOT` — standardize all to `CA-ROOT`
  - Blast radius: main.py (remove `--pki-enroll`, add `--pki-scep`), render.py (fix CA name + pass ca_ip to router templates), router templates (add trustpoint block)
- [ ] Support IOSv for PKI CA-ROOT (currently CSR1000v only)
  - Why: CA-ROOT is currently hardcoded to csr1000v node definition (see render.py ca_dev_def)
  - Current: csr-pki-ca.jinja2 template uses CSR interface names (GigabitEthernet1, Gi5)
  - Future: Make template adaptable to IOSv (GigabitEthernet0/1, Gi0/5) if PKI server works on IOSv
  - Requires: Pass dev_def to template context, add conditional interface naming in template
  - Blast radius: render.py (CA creation), csr-pki-ca.jinja2 (interface config), offline YAML generation
- [ ] 3-level PKI hierarchy: CA-ROOT → CA-POLICY → router enrollment
  - Why: Simulate enterprise PKI depth with root CA offline, policy/issuing CA online, routers auto-enrolling via SCEP
  - Naming: CA-ROOT (offline root), CA-POLICY (online issuing CA), CA-SIGN reserved for cross-cert scenarios
  - Requires: csr-pki-policy.jinja2 template, CA-POLICY node in render_dmvpn_network(), chained enrollment config
  - Blast radius: render.py (CA-POLICY node creation + links), templates (CA-ROOT signs CA-POLICY cert), main.py (--pki-depth or --pki-policy flag)
- [ ] Add `--pki-ca-fingerprint` and `enrollment fingerprint` to client trustpoint (SCEP TOFU)
  - Why: Lets clients authenticate the CA non-interactively so `crypto pki authenticate` and auto-enroll work on 300 routers without manual "yes".
  - Fallback: If EEM-based authenticate (applet that runs `crypto pki authenticate` and answers "yes" via pattern) cannot be made to work, implement this sooner so clients can authenticate by fingerprint instead.
  - Chicken-and-egg: Fingerprint must be known at lab generation time (to embed in client config). With on-box CA the CA cert does not exist until the lab is created and CA has booted — so fingerprint is unknown when running `topogen --pki ... --offline-yaml out.yaml 300`. With offline/imported root the user generates the root (and cert) before the lab, computes the fingerprint, then runs topogen with `--pki-ca-fingerprint <hex>`; clients get `enrollment fingerprint` in config and can authenticate without prompts.
  - Implication: This feature pairs with "imported root" flow (user builds root offline, imports cert+key onto CA router). Without imported root, fingerprint at gen time is not available.
  - Requires: main.py (--pki-ca-fingerprint), render.py (_inject_pki_client_trustpoint: add enrollment fingerprint when set), docs.
  - Blast radius: main.py, render.py, client config output.
- [ ] Add `--strong` / `--stronger` crypto flags for PKI and IKEv2 (low effort)
  - Why: Default IOS XE RSA 2048 / AES-128 may not match security-conscious lab goals; named profiles simplify selection
  - `--strong`: RSA 2048, AES-256, SHA-256 (NIST current)
  - `--stronger`: RSA 4096, AES-256-GCM, SHA-384 (NIST future-proof)
  - Blast radius: main.py (argparse), templates (crypto profile conditionals)
- [ ] Add NAT mode support for external-connector (in addition to current System Bridge mode)
  - Why: Enable outbound-only connectivity for OOB management networks where devices need to reach external resources but don't need to be reachable from outside
  - Current implementation uses "System Bridge" mode (bidirectional connectivity)
  - NAT mode would be useful for security-focused deployments where management plane should only initiate outbound connections
- [ ] Refactor: deduplicate offline YAML emission for `--mgmt-bridge` (external_connector + SWoob0 port offset + links)
  - Today this logic is repeated across multiple offline renderers in `src/topogen/render.py`
  - Goal: centralize into a shared helper to reduce risk of fixing one mode and missing others
- [ ] (add ideas here)
- [ ] Add archive config to all templates. Use this block:
  ```
  archive
   log config
    logging enable
    notify syslog contenttype plaintext
    hidekeys
   path flash:
   maximum 5
   write-memory
  ```
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

- [ ] TOPOGEN_INTENT invisible annotation contract for CML labs (medium effort)
  - Why: Embed generation parameters as an invisible text annotation inside the CML lab description so any tool (CLI, GUI, script) can recover the original intent directly from the live lab — not just from the offline YAML.
  - Contract: A hidden `TOPOGEN_INTENT={...}` JSON block injected into the lab description/notes field, invisible in the CML UI but parseable by CLI.
  - Data fields: mode, nodes, template, routing protocol, --pki, --mgmt, addressing params, topogen version.
  - On import: `topogen regenerate` reads the annotation from the live CML lab and re-generates or updates deterministically.
  - Complements: "Embed serialized intent in YAML" (above) — YAML embedding covers offline files; this covers live CML labs.
  - Blast radius: render.py (inject annotation on online lab creation), main.py (--regenerate reads annotation from CML API).

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

- [x] Add `--import` and `--import-yaml` flags for offline-to-CML workflow (medium effort).
  - Why: Currently there's no way to take an offline YAML and push it into CML without switching to online mode.
    This bridges the gap: generate offline → inspect/edit → import → start.
  - Implemented:
    - `--import-yaml <file>`: Read an existing offline YAML (skip generation); use with `--import`
    - `--import`: Import the generated/read YAML into CML via `virl2_client` (requires `--offline-yaml` or `--import-yaml`)
    - Print file size (KB) before import and lab URL after import (same as online mode)
    - `--start` works after import; start runs in background so CLI returns immediately (check CML UI for status)
  - Examples:
    - Generate + import + start: `topogen ... --offline-yaml out/lab.yaml --import --start`
    - Read existing + import: `topogen --import-yaml out/lab.yaml --import`
    - Read + import + start: `topogen --import-yaml out/lab.yaml --import --start`
  - Blast radius: main.py (argparse dispatch), render.py (import path via virl2_client), no changes to offline generation.

- [x] Add `--up <file>` shorthand and `--print-up-cmd` flag (low effort, sugar).
  - Implemented: `--up FILE` is sugar for `--import-yaml FILE --import --start`.
  - `--print-up-cmd`: with `--offline-yaml`, after generation prints "When you're ready: topogen --up <file>" (only when `--up` not used on this run).
  - Example: generate `topogen ... --offline-yaml out/lab.yaml --print-up-cmd`, then deploy with `topogen --up out/lab.yaml`.
  - Blast radius: main.py (argparse + dispatch).

- [ ] Trim and reorganize README.md for readability (low effort).
  - Why: README has grown large with inline help output, detailed examples, and mixed audiences (end-users vs contributors). Makes it harder to scan and find what you need.
  - Options: (a) Move contributor/developer content to DEVELOPER.md, (b) Collapse verbose sections behind summary headings, (c) Replace inline `--help` block with a link (pairs with the help-drift item above).
  - Blast radius: README.md only (documentation, no code changes).
