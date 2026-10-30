# Builds dist\ChessMaster\ChessMaster.exe (one-folder, windowed) with Stockfish bundled.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$engine = Join-Path $root "engine\stockfish.exe"

if (-not (Test-Path $python)) { throw "Missing $python. Run: py -3 -m venv .venv; .venv\Scripts\pip install -e '.[dev]'" }
if (-not (Test-Path $engine)) {
    Write-Host "Stockfish not found; downloading..."
    & (Join-Path $PSScriptRoot "get_stockfish.ps1")
}

Push-Location $root
try {
    & $python -m PyInstaller `
        --noconfirm --clean --windowed `
        --name ChessMaster `
        --paths src `
        --add-data "engine;engine" `
        --add-data "src\chessmaster\profiles;chessmaster\profiles" `
        --exclude-module tkinter `
        --distpath dist --workpath build `
        src\chessmaster\__main__.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    Write-Host "Built $(Join-Path $root 'dist\ChessMaster\ChessMaster.exe')"
}
finally {
    Pop-Location
}
