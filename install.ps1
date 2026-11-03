# Install sonar for the current Windows user (no administrator rights needed).
#
#   Without git, in one line (PowerShell):
#       irm https://raw.githubusercontent.com/tfem1/sonar/main/install.ps1 | iex
#   From a clone or an extracted ZIP:
#       powershell -ExecutionPolicy Bypass -File install.ps1
#   Uninstall:
#       powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#       (one-liner:  $env:SONAR_UNINSTALL=1; irm https://raw.githubusercontent.com/tfem1/sonar/main/install.ps1 | iex)
#
# No param() block and no 'exit': the script must also work through Invoke-Expression,
# where 'exit' would close the user's PowerShell window.

$SonarScriptRoot = $PSScriptRoot  # empty when run through iex

& {
    $ErrorActionPreference = "Continue"
    $Repo = "tfem1/sonar"
    $Ref = if ($env:SONAR_REF) { $env:SONAR_REF } else { "main" }
    $Dir = Join-Path $env:LOCALAPPDATA "Programs\sonar"
    $Uninstall = ($args -contains "-Uninstall") -or ($env:SONAR_UNINSTALL -eq "1")

    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($null -eq $UserPath) { $UserPath = "" }
    $Parts = @($UserPath.Split(";") | Where-Object { $_ -ne "" })

    if ($Uninstall) {
        if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
        $Rest = @($Parts | Where-Object { $_.TrimEnd("\") -ne $Dir })
        [Environment]::SetEnvironmentVariable("Path", ($Rest -join ";"), "User")
        Remove-Item Env:SONAR_UNINSTALL -ErrorAction SilentlyContinue
        Write-Host "sonar removed from $Dir"
        return
    }

    # Python: prefer the py launcher, then python.exe (skipping the Microsoft Store stub).
    $Python = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" 2>$null
        if ($LASTEXITCODE -eq 0) { $Python = "py -3" }
    }
    if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -c "import sys; sys.exit(sys.version_info < (3, 9))" 2>$null
        if ($LASTEXITCODE -eq 0) { $Python = "python" }
    }
    if (-not $Python) {
        throw "Python 3.9+ is required. Install it with:  winget install Python.Python.3.13  (or from https://www.python.org/downloads/windows/), then open a new terminal and run this again."
    }

    $ErrorActionPreference = "Stop"
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $Dest = Join-Path $Dir "sonar.py"

    # Use the sonar.py next to this script (clone / ZIP); when run through iex, download it.
    $Local = if ($SonarScriptRoot) { Join-Path $SonarScriptRoot "sonar.py" } else { $null }
    if ($Local -and (Test-Path $Local)) {
        Copy-Item -Force $Local $Dest
    } else {
        $Url = "https://raw.githubusercontent.com/$Repo/$Ref/sonar.py"
        Write-Host "downloading $Url"
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Dest
    }

    $Shim = Join-Path $Dir "sonar.cmd"
    Set-Content -Encoding ASCII -Path $Shim -Value "@echo off`r`n$Python `"%~dp0sonar.py`" %*"

    $Version = & cmd /c "`"$Shim`" -V"
    if ($LASTEXITCODE -ne 0) { throw "sonar does not start: $Version" }

    if (-not ($Parts | Where-Object { $_.TrimEnd("\") -eq $Dir })) {
        [Environment]::SetEnvironmentVariable("Path", (($Parts + $Dir) -join ";"), "User")
    }
    if (-not (($env:Path -split ";") -contains $Dir)) { $env:Path = "$env:Path;$Dir" }  # usable right away
    Write-Host "$Version installed to $Dir"
    Write-Host "run it with: sonar   (Windows Terminal recommended)"
} @args
