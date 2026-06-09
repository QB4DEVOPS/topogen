# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-08
#
# - Called by: pytest (tests/test_nac_terraform_plan.py)
# - Reads from: TOPOGEN_TERRAFORM_PLAN env, pytest -m selection
# - Writes to: None
#
# Purpose: Opt-in collection rules for NaC terraform plan contract tests (TG-161).
# Blast Radius: Test-only.

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "terraform: NaC terraform init/plan contract (needs terraform binary + network)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_terraform = os.environ.get("TOPOGEN_TERRAFORM_PLAN") == "1"
    markexpr = config.getoption("-m", default="")
    if run_terraform or (markexpr and "terraform" in markexpr):
        return

    skip = pytest.mark.skip(
        reason=(
            "terraform plan gate is opt-in: set TOPOGEN_TERRAFORM_PLAN=1 "
            "or run pytest -m terraform"
        )
    )
    for item in items:
        if "terraform" in item.keywords:
            item.add_marker(skip)
