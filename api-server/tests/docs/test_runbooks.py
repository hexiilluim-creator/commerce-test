from pathlib import Path

import pytest
import yaml

RUNBOOKS_DIR = Path(__file__).parent.parent.parent / "docs" / "runbooks"

@pytest.mark.unit
def test_runbook_frontmatter():
    for runbook_file in RUNBOOKS_DIR.glob("*.md"):
        if runbook_file.name == "README.md":
            continue
        
        content = runbook_file.read_text()
        
        # Check for frontmatter presence
        assert content.startswith("---\n"), f"Runbook {runbook_file.name} missing frontmatter start"
        assert "\n---\n" in content, f"Runbook {runbook_file.name} missing frontmatter end"
        
        frontmatter_raw = content.split("\n---\n")[0].replace("---\n", "")
        frontmatter = yaml.safe_load(frontmatter_raw)
        
        assert "severity" in frontmatter, f"Runbook {runbook_file.name} missing severity in frontmatter"
        assert "owner" in frontmatter, f"Runbook {runbook_file.name} missing owner in frontmatter"
        assert "MTTD" in frontmatter, f"Runbook {runbook_file.name} missing MTTD in frontmatter"
        assert "MTTR" in frontmatter, f"Runbook {runbook_file.name} missing MTTR in frontmatter"
        
        assert frontmatter["severity"] in ["critical", "warning", "info"], f"Runbook {runbook_file.name} has invalid severity"
        assert isinstance(frontmatter["MTTD"], str), f"Runbook {runbook_file.name} has invalid MTTD type"
        assert isinstance(frontmatter["MTTR"], str), f"Runbook {runbook_file.name} has invalid MTTR type"
