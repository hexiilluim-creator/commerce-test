    #!/usr/bin/env bash
    set -euo pipefail

    ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    MODE="${1:---check}"
    EVIDENCE_DIR="${2:-$ROOT_DIR/release-evidence/v27.1.0}"
    mkdir -p "$EVIDENCE_DIR"

    python3 - "$ROOT_DIR" "$EVIDENCE_DIR" <<'PY'
import csv
import hashlib
import os
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
patterns = {
    'openai_like': re.compile(r'sk-[A-Za-z0-9_-]+'),
    'aws_access_key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'github_pat': re.compile(r'ghp_[A-Za-z0-9]+'),
    'google_api_key': re.compile(r'AIza[0-9A-Za-z_-]+'),
    'jwt_like': re.compile(r'eyJ[0-9A-Za-z._-]+'),
}
allow = {
    '.git', '__pycache__', 'node_modules', '.venv', 'release-evidence'
}
rows = []
for path in root.rglob('*'):
    if any(part in allow for part in path.parts):
        continue
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    for name, rx in patterns.items():
        if rx.search(text):
            rows.append([str(path.relative_to(root)), name, 'match'])

csv_path = out_dir / 'audit_secrets.csv'
with csv_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['path', 'pattern', 'status'])
    w.writerows(rows)

sha_path = out_dir / 'sha256_manifest.txt'
with sha_path.open('w', encoding='utf-8') as f:
    for path in sorted(p for p in root.rglob('*') if p.is_file() and 'release-evidence' not in p.parts):
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        f.write(f"{h}  {path.relative_to(root)}\n")

print(f"[audit] secrets_hits={len(rows)}")
print(f"[audit] csv={csv_path}")
PY

    if [[ "$MODE" == "--check" ]]; then
      echo "[audit] package audit completed"
    fi
