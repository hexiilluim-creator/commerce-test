from pathlib import Path

import pytest

RUNBOOKS_DIR = Path(__file__).parent.parent.parent / "docs" / "runbooks"

@pytest.mark.unit
def test_runbook_sections():
    for runbook_file in RUNBOOKS_DIR.glob("*.md"):
        if runbook_file.name == "README.md":
            continue
        
        content = runbook_file.read_text()
        
        assert "## Symptômes" in content, f"Runbook {runbook_file.name} missing Symptômes section"
        assert "## Cause probable" in content, f"Runbook {runbook_file.name} missing Cause probable section"
        assert "## Étapes diagnostic" in content, f"Runbook {runbook_file.name} missing Étapes diagnostic section"
        assert "## Étapes mitigation" in content, f"Runbook {runbook_file.name} missing Étapes mitigation section"
        assert "## Post-mortem template" in content, f"Runbook {runbook_file.name} missing Post-mortem template section"
