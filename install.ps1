# Install sonar for the current Windows user (no administrator rights needed).
#   powershell -ExecutionPolicy Bypass -File install.ps1             install / update
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$Dir = Join-Path $env:LOCALAPPDATA "Programs\sonar"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $UserPath) { $UserPath = "" }
$Parts = @($UserPath.Split(";") | Where-Object { $_ -ne "" })

if ($Uninstall) {
    if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
    $Rest = @($Parts | Where-Object { $_.TrimEnd("\") -ne $Dir })
    [Environment]::SetEnvironmentVariable("Path", ($Rest -join ";"), "User")
    Write-Host "sonar removed from $Dir"
    exit 0
}

# Prefer the py launcher, fall back to python on PATH (skipping the Microsoft Store stub).
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py -3" }
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = "python" }
}
if (-not $Python) { Write-Error "Python 3 is required: https://www.python.org/downloads/windows/" }

$Src = Join-Path $PSScriptRoot "sonar.py"
if (-not (Test-Path $Src)) { Write-Error "sonar.py not found next to install.ps1" }

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Copy-Item -Force $Src (Join-Path $Dir "sonar.py")
Set-Content -Encoding ASCII -Path (Join-Path $Dir "sonar.cmd") -Value "@echo off`r`n$Python `"%~dp0sonar.py`" %*"

if (-not ($Parts | Where-Object { $_.TrimEnd("\") -eq $Dir })) {
    [Environment]::SetEnvironmentVariable("Path", (($Parts + $Dir) -join ";"), "User")
    Write-Host "added $Dir to your user PATH (open a new terminal to use it)"
}
$Version = & cmd /c "`"$(Join-Path $Dir 'sonar.cmd')`" -V"
Write-Host "$Version installed to $Dir"
