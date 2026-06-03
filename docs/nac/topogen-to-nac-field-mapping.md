<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.0
Date Modified: 2026-06-03

- Called by: Developers implementing NaC adapters and tests
- Reads from: src/topogen/models.py and render-layer internal structures
- Writes to: None (documentation only)
- Calls into: docs/nac/iosxe-one-router-golden-contract.md

Purpose: Define the TopoGen-to-NaC field projection matrix for TG-116 scope.
Blast Radius: Mapping changes affect canonical fixture generation and adapters.
-->

# TopoGen to NaC field mapping

This matrix defines how TopoGen-internal fields map to canonical NaC YAML fields.
Status values are:

- `Required`: must be projected for MVP
- `Optional`: can be projected in MVP but not required for compliance
- `Deferred`: intentionally out of scope for MVP

| topogen_internal_field | nac_yaml_field | status |
|---|---|---|
| `TopogenNode.hostname` | `iosxe.devices[0].hostname` | Required |
| `TopogenNode.hostname` | `iosxe.devices[0].name` | Required |
| `device platform selector (iosv/csr1000v)` | `iosxe.devices[0].device_template` | Required |
| `template name (-T/--template)` | `iosxe.devices[0].template` | Required |
| `platform family resolver` | `iosxe.devices[0].platform` | Required |
| `role resolver (topology role)` | `iosxe.devices[0].role` | Required |
| `TopogenNode.loopback` | `iosxe.devices[0].loopbacks[0].ipv4` | Required |
| `TopogenNode.interfaces[*].address` | `iosxe.devices[0].interfaces[*].ipv4` | Optional |
| `TopogenNode.interfaces[*].description` | `iosxe.devices[0].interfaces[*].description` | Optional |
| `TopogenNode.interfaces[*].slot` | `iosxe.devices[0].interfaces[*].slot` | Optional |
| `management address resolver` | `iosxe.devices[0].mgmt.ipv4` | Required |
| `management VRF resolver` | `iosxe.devices[0].mgmt.vrf` | Optional |
| `CML node id/reference` | `iosxe.devices[0].metadata.topogen.node_id` | Optional |
| `render mode (flat/simple/nx/dmvpn)` | `iosxe.devices[0].metadata.topogen.mode` | Optional |
| `node coordinates` | `iosxe.devices[0].metadata.topogen.coords` | Deferred |
| `dns host linkage` | `iosxe.devices[0].metadata.topogen.dns_host` | Deferred |
| `PKI/GETVPN feature flags` | `iosxe.devices[0].metadata.topogen.security_features` | Deferred |

## Notes

- `name` mirrors `hostname` for the one-router golden contract to keep host keying deterministic.
- Deferred fields are intentionally excluded from MVP fixture stability and adapter acceptance criteria.
