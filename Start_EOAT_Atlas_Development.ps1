[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python is not available on PATH.'
}
Set-Location -LiteralPath $PSScriptRoot
& python run_atlas.py
exit $LASTEXITCODE
