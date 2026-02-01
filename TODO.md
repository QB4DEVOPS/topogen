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

1. EIGRP stub flag support (this is the current work)
2. DMVPN IPsec protection (IKEv2 + PSK)
3. DMVPN security roadmap (PKI)
4. Decide/implement least-astonishment semantics for DMVPN `--dmvpn-underlay flat-pair` node counts

## Current work

- [ ] Implement EIGRP stub flag support
  - add CLI flag: `--eigrp-stub`
  - stub form: `eigrp stub connected summary`
  - render EIGRP stub in templates (IOSv + CSR) (incremental)
    - first: DMVPN underlay `flat-pair`: apply stub on even routers (companion `*-eigrp` templates)
    - then: apply stub on odd DMVPN routers (`*-dmvpn` templates)
  - add README + CHANGES updates when complete

## Promote to Issues

- [ ] (add issue-worthy items here)

- [ ] Usability fix: allow `python -m topogen ...` (no `.main`) by adding `src/topogen/__main__.py`

## Done

- [ ] (move completed items here if you want a cleaner active list)

- [x] DMVPN VRF support (flat-pair): odd (DMVPN) routers only
  - VRF on pair-link + Loopback0 + Tunnel0
  - even routers remain global (no VRF)
  - ensure EIGRP split-horizon is correct in VRF mode

- [x] Commit/push PR for `feat/dmvpn-underlay`

## Future ideas

- [ ] (add ideas here)
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
