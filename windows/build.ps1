# Build Budget for Windows from source.     powershell -ExecutionPolicy Bypass -File windows\build.ps1
#
# Needs Python 3.12 (python.org) on the PATH. Produces dist\Budget\Budget.exe, and
# dist\Budget-Setup-<version>.exe too if Inno Setup 6 is installed.
# Most people don't need this: download the installer from the GitHub Releases page.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$version = (Get-Content VERSION).Trim()

if (-not (Test-Path .venv\Scripts\python.exe)) {
    Write-Host "==> Creating virtualenv"
    python -m venv .venv
}
$py = ".venv\Scripts\python.exe"
Write-Host "==> Installing dependencies"
& $py -m pip install -q -r requirements.txt -r requirements-dev.txt

Write-Host "==> Running tests"
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

Write-Host "==> Building Budget.exe"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $py -m PyInstaller windows\Budget.spec --noconfirm --clean --log-level WARN --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "==> Checking that the built app starts"
$p = Start-Process dist\Budget\Budget.exe -ArgumentList "--smoke-test" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Smoke test failed (exit code $($p.ExitCode))" }

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    Write-Host "==> Building the installer"
    & $iscc /Q "/DVersion=$version" windows\installer.iss
    Write-Host "Done: dist\Budget-Setup-$version.exe"
} else {
    Write-Host "Done: dist\Budget\Budget.exe  (install Inno Setup 6 to also get an installer)"
}
