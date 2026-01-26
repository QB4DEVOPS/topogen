# Changes

This file lists changes.

- Unreleased
  - feat(flat): add new mode "flat-pair" (odd-even pairing). Odd: Gi0/0 -> access switch and Gi0/1 -> even's Gi0/0. Even: no leaf link. Last odd without partner leaves Gi0/1 unused.
  - feat(vrf): add optional VRF support for flat-pair pair links (odd router Gi0/1)
    - enable with `--vrf`
    - set VRF name with `--pair-vrf NAME`
    - lab descriptions (online and offline YAML) include VRF flags when enabled
  - docs: offline YAML output is recommended to be written under the `out/` directory (see README examples)

- version 0.2.4
  - empty

- version 0.2.3
  - feat(flat): add flat mode for topology generation
  - deterministic addressing and EIGRP template updates
  - docs: add CONTRIBUTING.md and update README/examples
  - config: add config.sample.toml with sane defaults
  - templates/flags: add addressing flags and custom-template warning
  - feat: add offline YAML export for CML 2.9 (schema flag)
  - chore: ignore generated offline YAML and untrack sample YAML
  - chore(gitignore): ignore NX lab YAML exports ([Nn][Xx]-*.yaml)
  - feat(template): add iosv-eigrp-stub template (enable EIGRP stub connected summary)
  - docs(readme): note non-flat EIGRP default-route limitation (user must originate default)
  - feat(template): add iosv-eigrp-nonflat for simple/NX (EIGRP 100 on 10.0.0.0/8 and 172.16.0.0/12; passive Lo0)
  - docs(readme): add non-flat EIGRP examples and note that large online builds may not show UI updates until ~25%
  - docs(readme): add flat mode examples

- version 0.2.1 (identical to 0.2.0, but make gh actions happy)
- version 0.2.0
  - properly configure name server / domain name
  - properly inject default route
  - fix indentation for boot.sh script
  - adapted some typing
  - renamed iol.jinja2 to iol-xe.jnja.2
  - added special LXC FRR variant
  - constrain number of node CLI arg
  - fix weird bug when DNS host is selected as the central node
  - updated dependencies
- version 0.1.4
  - added an IOL template
  - removed requests and associated libraries
  - add support to generate IOL nodes
  - fixed "ignore" SSL errors cmd line flag
- version 0.1.3 and earlier were the initial release
