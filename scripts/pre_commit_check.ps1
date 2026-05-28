Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -m pytest
python scripts/repo_safety_audit.py --staged
