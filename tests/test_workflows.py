"""Every GitHub button file must be valid, or GitHub silently drops the button."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_every_workflow_file_is_valid():
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data.get("name"), f"{path.name} has no name"
        assert data.get(True) or data.get("on"), f"{path.name} has no trigger"
