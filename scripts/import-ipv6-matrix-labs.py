#!/usr/bin/env python3
"""Import the 15 IPv6 OOB matrix labs into CML (server 183).

Reads VIRL2_URL/VIRL2_USER/VIRL2_PASS from the environment and imports each
offline YAML topology. Skips labs whose title already exists unless --replace.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from virl2_client import ClientLibrary

LABS = [
    "tf-simple-static-extmgmt",
    "tf-simple-slaac-extmgmt",
    "tf-simple-dhcpv6-extmgmt",
    "tf-nx-static-extmgmt",
    "tf-nx-slaac-extmgmt",
    "tf-nx-dhcpv6-extmgmt",
    "tf-flat-static-extmgmt",
    "tf-flat-slaac-extmgmt",
    "tf-flat-dhcpv6-extmgmt",
    "tf-flat-pair-static-extmgmt",
    "tf-flat-pair-slaac-extmgmt",
    "tf-flat-pair-dhcpv6-extmgmt",
    "tf-dmvpn-static-extmgmt",
    "tf-dmvpn-slaac-extmgmt",
    "tf-dmvpn-dhcpv6-extmgmt",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="out",
        help="Directory containing per-lab offline YAML folders.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete an existing lab with the same title before importing.",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start each lab after a successful import.",
    )
    args = parser.parse_args()

    url = os.environ.get("VIRL2_URL", "https://192.168.1.183")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    if not user or not password:
        print("ERROR: VIRL2_USER / VIRL2_PASS must be set", file=sys.stderr)
        return 2

    client = ClientLibrary(url, user, password, ssl_verify=False)
    client.is_system_ready(wait=True)

    existing = {lab.title: lab for lab in client.all_labs()}

    out_dir = Path(args.out_dir)
    imported = 0
    failed = 0
    for name in LABS:
        yaml_path = out_dir / name / f"{name}.yaml"
        if not yaml_path.is_file():
            print(f"XX  {name}: missing {yaml_path}")
            failed += 1
            continue

        if name in existing:
            if args.replace:
                old = existing[name]
                try:
                    old.stop(wait=True)
                except Exception:
                    pass
                try:
                    old.wipe(wait=True)
                except Exception:
                    pass
                old.remove()
                print(f"--  {name}: removed pre-existing lab")
            else:
                print(f"==  {name}: already present, skipping (use --replace)")
                continue

        try:
            topology = yaml_path.read_text(encoding="utf-8")
            lab = client.import_lab(topology, title=name)
            msg = f"OK  {name}: imported as {lab.id}"
            if args.start:
                lab.start(wait=False)
                msg += " (start requested)"
            print(msg)
            imported += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"XX  {name}: import failed: {exc}")
            failed += 1

    print(f"\n{imported} imported, {failed} failed, {len(LABS)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
