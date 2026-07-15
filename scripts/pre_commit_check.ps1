Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -m pytest
python scripts/check_version_bump.py --staged
python scripts/repo_safety_audit.py --staged
