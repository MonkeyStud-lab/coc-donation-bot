# ============================================================================
# CoC Donation Bot — Windows Setup Script (LDPlayer + ADB)
# ============================================================================
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Force
# ============================================================================

param(
    [switch]$Force,
    [switch]$SkipIcons
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Stamp = Join-Path $Root ".setup_windows_stamp"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARNING: $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "    FAIL: $msg" -ForegroundColor Red }

# --- Check Windows ---
if ($env:OS -ne "Windows_NT") {
    Write-Fail "This script is for Windows only."
    exit 1
}

# --- Stamp fingerprint for idempotency ---
$pyprojectHash = (Get-FileHash "pyproject.toml" -Algorithm MD5).Hash
$setupHash = (Get-FileHash "scripts\setup_windows.ps1" -Algorithm MD5).Hash
$fingerprint = "pyproject=$pyprojectHash setup=$setupHash"

if (-not $Force -and (Test-Path $Stamp)) {
    $existing = Get-Content $Stamp -Raw
    if ($existing.Trim() -eq $fingerprint) {
        Write-Ok "Setup already complete (use -Force to redo)"
        exit 0
    }
}

# ====================================================================
# Step 1 — Find Python
# ====================================================================
Write-Step "Checking Python..."

$python = $null
$candidates = @("python", "python3", "py -3")
foreach ($c in $candidates) {
    try {
        $ver = & cmd /c "$c --version 2>&1"
        if ($ver -match "Python 3\.1[0-9]") {
            $python = $c
            Write-Ok "Found: $ver ($c)"
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Fail "Python 3.10+ not found."
    Write-Host ""
    Write-Host "  Download from: https://www.python.org/downloads/" -ForegroundColor White
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ====================================================================
# Step 2 — Find or locate ADB (LDPlayer)
# ====================================================================
Write-Step "Checking ADB (LDPlayer)..."

$adbDir = $null
$ldPaths = @(
    "$env:LOCALAPPDATA\LDPlayer\LDPlayer9",
    "C:\LDPlayer\LDPlayer9",
    "D:\LDPlayer\LDPlayer9",
    "$env:PROGRAMFILES\LDPlayer\LDPlayer9",
    "C:\LDPlayer\LDPlayer4.0",
    "D:\LDPlayer\LDPlayer4.0"
)

foreach ($p in $ldPaths) {
    $adbExe = Join-Path $p "adb.exe"
    if (Test-Path $adbExe) {
        $adbDir = $p
        break
    }
}

if ($adbDir) {
    Write-Ok "LDPlayer ADB found: $adbDir"
    # Add to PATH for this session
    $env:PATH = "$adbDir;$env:PATH"
} else {
    Write-Warn "LDPlayer ADB not found in common paths."
    Write-Host "    The bot will try to find ADB on PATH. Make sure LDPlayer is installed."
    Write-Host "    You can also set ADB_PATH env var to the adb.exe location."
}

# ====================================================================
# Step 3 — Create Python venv
# ====================================================================
Write-Step "Creating Python virtual environment..."

if ($Force -and (Test-Path ".venv")) {
    Remove-Item -Recurse -Force ".venv"
}

if (-not (Test-Path $VenvPy)) {
    & cmd /c "$python -m venv .venv"
    if (-not (Test-Path $VenvPy)) {
        Write-Fail "Failed to create virtual environment."
        exit 1
    }
    Write-Ok "Virtual environment created"
} else {
    Write-Ok "Virtual environment already exists"
}

# ====================================================================
# Step 4 — Install Python dependencies
# ====================================================================
Write-Step "Installing Python packages (this may take a few minutes)..."

$pip = Join-Path $Root ".venv\Scripts\pip.exe"
& cmd /c "$VenvPy -m pip install --upgrade pip setuptools wheel" 2>&1 | Out-Null
& cmd /c "$pip install -e $Root" 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install failed."
    exit 1
}
Write-Ok "Python packages installed"

# ====================================================================
# Step 5 — Pre-download EasyOCR model
# ====================================================================
Write-Step "Preloading EasyOCR English model (first time takes 1-3 min)..."

$preloadScript = @"
import easyocr
easyocr.Reader(['en'], gpu=False, verbose=False)
print("EasyOCR model ready")
"@

try {
    $preloadScript | & cmd /c "$VenvPy" 2>&1 | Out-Null
    Write-Ok "EasyOCR model ready"
} catch {
    Write-Warn "EasyOCR preload had issues (bot can still run, OCR may download on first use)"
}

# ====================================================================
# Step 6 — Sync game data
# ====================================================================
Write-Step "Syncing unit housing data..."

try {
    & cmd /c "$VenvPy scripts\sync_game_data.py --force" 2>&1 | Out-Null
    Write-Ok "Unit data synced"
} catch {
    Write-Warn "Unit data sync had warnings (bundled seed data will be used)"
}

# ====================================================================
# Step 7 — Download unit icons
# ====================================================================
if (-not $SkipIcons) {
    Write-Step "Downloading unit icons..."

    try {
        & cmd /c "$VenvPy scripts\sync_game_data.py --icons-only --force" 2>&1 | Out-Null
        Write-Ok "Unit icons downloaded"
    } catch {
        Write-Warn "Icon download had issues (open-request icon matching may be limited)"
    }
}

# ====================================================================
# Step 8 — Save stamp
# ====================================================================
$fingerprint | Out-File -FilePath $Stamp -Encoding ascii -NoNewline

# ====================================================================
# Done!
# ====================================================================
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Open LDPlayer and install/start Clash of Clans"
Write-Host "    2. Calibrate:   .venv\Scripts\python.exe scripts\calibrate.py"
Write-Host "    3. Run the bot:  .venv\Scripts\python.exe -m coc_bot.main"
Write-Host ""
Write-Host "  Or just double-click 'start_bot.bat' in the project folder!"
Write-Host ""
Write-Host "  Note: LDPlayer + Clash of Clans must already be installed." -ForegroundColor Yellow
