# Downloads the latest official Stockfish Windows build into engine\stockfish.exe.
# Recent releases ship one "universal" x86-64 build; older ones ship per-CPU builds,
# in which case AVX2 is tried first and SSE4.1 is the fallback.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$engineDir = Join-Path $root "engine"
New-Item -ItemType Directory -Force -Path $engineDir | Out-Null
$target = Join-Path $engineDir "stockfish.exe"

function Test-Engine([string]$exe) {
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exe
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        $p.StandardInput.WriteLine("uci")
        $p.StandardInput.WriteLine("quit")
        $out = $p.StandardOutput.ReadToEnd()
        $p.WaitForExit(5000) | Out-Null
        return $out -match "uciok"
    } catch {
        return $false
    }
}

$release = Invoke-RestMethod -Uri "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest" -UseBasicParsing
Write-Host "Latest release: $($release.tag_name)"
$assets = @()
foreach ($variant in @("universal", "avx2", "sse41-popcnt", "")) {
    $suffix = if ($variant) { "-$variant" } else { "" }
    $asset = $release.assets | Where-Object { $_.name -eq "stockfish-windows-x86-64$suffix.zip" }
    if ($asset) { $assets += $asset }
}
if (-not $assets) { throw "No Windows x86-64 asset found in release $($release.tag_name)" }

foreach ($asset in $assets) {
    $zip = Join-Path $env:TEMP $asset.name
    $extract = Join-Path $env:TEMP ([IO.Path]::GetFileNameWithoutExtension($asset.name))
    Write-Host "Downloading $($asset.browser_download_url)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
    Expand-Archive -Path $zip -DestinationPath $extract
    $exe = Get-ChildItem -Path $extract -Recurse -Filter "stockfish*.exe" | Select-Object -First 1
    if (-not $exe) { Write-Host "No executable in $($asset.name)"; continue }
    if (Test-Engine $exe.FullName) {
        Copy-Item $exe.FullName $target -Force
        Get-ChildItem -Path $extract -Recurse -Filter "Copying.txt" | Select-Object -First 1 |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $engineDir "COPYING.txt") -Force }
        Write-Host "Installed $($asset.name) to $target"
        exit 0
    }
    Write-Host "$($asset.name) did not respond to 'uci'; trying the next build."
}
throw "Could not install a working Stockfish build."
