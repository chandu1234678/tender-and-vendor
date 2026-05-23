param(
	[switch]$GenerateSampleData,
	[switch]$InstallDevDependencies
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path .venv)) {
	python -m venv .venv
}

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

if ($InstallDevDependencies -and (Test-Path requirements-dev.txt)) {
	pip install -r requirements-dev.txt
}

New-Item -ItemType Directory -Force -Path data\incoming, data\parsed, data\output | Out-Null

if ($GenerateSampleData -and (Test-Path scripts\generate_sample_data.py)) {
	python scripts\generate_sample_data.py
}

Write-Host 'Bootstrap complete.'
