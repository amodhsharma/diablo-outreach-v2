"""Every GitHub button file must be valid, or GitHub silently drops the button."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_every_workflow_file_is_valid():
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data.get("name"), f"{path.name} has no name"
        assert data.get(True) or data.get("on"), f"{path.name} has no trigger"


def _runs(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job in data["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                yield step["run"]


def test_every_run_block_is_valid_shell_and_calls_real_code():
    import re
    import subprocess
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for script in _runs(path):
            plain = re.sub(r"\$\{\{.*?\}\}", "x", script)
            check = subprocess.run(["bash", "-n"], input=plain, text=True, capture_output=True)
            assert check.returncode == 0, f"{path.name}: {check.stderr}"
            for module, flags in re.findall(r"python -m outreach\.(\w+)([^\n]*)", script):
                source = ROOT / "outreach" / f"{module}.py"
                assert source.exists(), f"{path.name} calls outreach.{module}, which does not exist"
                for flag in re.findall(r"--[a-z-]+", flags):
                    assert flag in source.read_text(encoding="utf-8"), f"{path.name}: outreach.{module} has no {flag}"


def test_the_timer_inputs_exist():
    research = yaml.safe_load((ROOT / ".github/workflows/research.yml").read_text())
    outreach = yaml.safe_load((ROOT / ".github/workflows/outreach.yml").read_text())
    assert "Automatic run" in research[True]["workflow_dispatch"]["inputs"]["action"]["options"]
    assert outreach[True]["workflow_dispatch"]["inputs"]["check_only"]["type"] == "boolean"  # button 3's timer body
    send_loop = yaml.safe_load((ROOT / ".github/workflows/send-loop.yml").read_text())
    inputs = send_loop[True]["workflow_dispatch"]["inputs"]
    assert inputs["check_only"]["type"] == "boolean" and "CONFIRM" in inputs["test_gaps"]["description"]
    # Buttons 3 and 4 never run at the same time.
    assert outreach["concurrency"]["group"] == send_loop["concurrency"]["group"]
    # Button 3 never emails anyone; button 4 does all the sending.
    assert "outreach.send" not in (ROOT / ".github/workflows/outreach.yml").read_text()
    assert "outreach.sync" not in (ROOT / ".github/workflows/outreach.yml").read_text()


def test_only_the_four_buttons_are_left():
    names = sorted(yaml.safe_load(p.read_text())["name"] for p in (ROOT / ".github" / "workflows").glob("*.yml"))
    # Plus the strain test helper (19 Oct 2026), which only ever works on the test account.
    assert names == ["1 - Setup HubSpot (once per account)", "2 - Research", "3 - Find contacts",
                     "4 - Send and follow up", "T - Strain test: give test contacts the test addresses (test account only)"]
    helper = (ROOT / ".github" / "workflows" / "test-addresses.yml").read_text()
    assert "HUBSPOT_TOKEN_TEST" in helper and "HUBSPOT_TOKEN_LIVE" not in helper
