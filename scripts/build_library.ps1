<#
.SYNOPSIS
Scan a directory for ZIM files and add them all to library.xml.

.DESCRIPTION
Finds every *.zim file in the given directory and registers it with
kiwix-manage. The library file is created on first run.

.PARAMETER ZimDir
Path to the directory containing your ZIM files.

.PARAMETER Library
Path to the library XML file to create/update. Defaults to library.xml.

.EXAMPLE
.\scripts\build_library.ps1 C:\zims
.\scripts\build_library.ps1 D:\usb\zims  C:\data\library.xml
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ZimDir,

    [string]$Library = "library.xml"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ZimDir -PathType Container)) {
    Write-Error "Directory not found: $ZimDir"
    exit 1
}

# Locate kiwix-manage.
# Priority: $env:KIWIX_MANAGE → <repo>/kiwix-tools/ → PATH.
$kiwixManage = $null
if ($env:KIWIX_MANAGE) {
    if (-not (Test-Path $env:KIWIX_MANAGE)) {
        Write-Error "kiwix-manage not found. Add it to PATH or place kiwix-tools\ next to this repo."
        exit 1
    }
    $kiwixManage = $env:KIWIX_MANAGE
} else {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $localBin = Join-Path $repoRoot "kiwix-tools/kiwix-manage"
    if (-not (Test-Path $localBin)) {
        $localBin = Join-Path $repoRoot "kiwix-tools/kiwix-manage.exe"
    }
    if (Test-Path $localBin) {
        $kiwixManage = $localBin
    } elseif (Get-Command "kiwix-manage" -ErrorAction SilentlyContinue) {
        $kiwixManage = "kiwix-manage"
    } else {
        Write-Error "kiwix-manage not found. Add it to PATH or place kiwix-tools\ next to this repo."
        exit 1
    }
}

$zims = Get-ChildItem -Path $ZimDir -Filter "*.zim" | Sort-Object Name

if ($zims.Count -eq 0) {
    Write-Warning "No .zim files found in $ZimDir"
    exit 1
}

Write-Host "Building $Library from $($zims.Count) ZIM file(s) in $ZimDir ..." -ForegroundColor Cyan
Write-Host ""

foreach ($zim in $zims) {
    Write-Host "  + $($zim.Name)" -ForegroundColor White
    & $kiwixManage $Library add $zim.FullName
}

Write-Host ""
Write-Host "[OK] $Library updated - $($zims.Count) ZIM file(s) registered." -ForegroundColor Green
