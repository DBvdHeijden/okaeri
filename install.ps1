# Install okaeri on Windows without git or uv, in PowerShell:
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/DBvdHeijden/okaeri/main/install.ps1 | iex"
# Running it again reinstalls the service; update with `uv run main.py update`.
$ErrorActionPreference = "Stop"

$Repo = "DBvdHeijden/okaeri"
$Dir = if ($env:OKAERI_DIR) { $env:OKAERI_DIR } else { Join-Path $HOME "okaeri" }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$HOME\.local\bin;$env:Path"  # where the uv installer puts it; new terminals pick it up by themselves
}

if (-not (Test-Path $Dir)) {
    $sha = (Invoke-RestMethod "https://api.github.com/repos/$Repo/commits/main").sha
    # Unpack next to it first, so a failed download doesn't leave a half-filled folder behind.
    $download = "$Dir.download"
    if (Test-Path $download) { Remove-Item -Recurse -Force $download }
    New-Item -ItemType Directory $download | Out-Null
    Invoke-WebRequest "https://github.com/$Repo/archive/$sha.zip" -OutFile "$download\okaeri.zip" -UseBasicParsing
    Expand-Archive "$download\okaeri.zip" $download
    Set-Content "$download\okaeri-$sha\VERSION" $sha
    Move-Item "$download\okaeri-$sha" $Dir
    Remove-Item -Recurse -Force $download
}

Set-Location $Dir
uv run main.py install
