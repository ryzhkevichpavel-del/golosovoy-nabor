param(
    [string]$Model = "base"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -c "from golosovoy_nabor.whisper_assets import ensure_backend; ensure_backend('$Model', print)"
