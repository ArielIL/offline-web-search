# package_for_offline.ps1
# Script to package the Distributed Offline Search System for deployment

$distDir = "dist"
$serverDir = "$distDir\server"
$clientDir = "$distDir\client"

# 1. Clean and Create Dist Directories
Write-Host "Creating distribution directories..."
if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
New-Item -ItemType Directory -Path $serverDir -Force
New-Item -ItemType Directory -Path $clientDir -Force

# 2. Package Server Components
Write-Host "Packaging Server..."
Copy-Item "search_server.py" -Destination $serverDir
Copy-Item "build_local_index.py" -Destination $serverDir
Copy-Item "add_external_source.py" -Destination $serverDir
Copy-Item "requirements.txt" -Destination $serverDir
Copy-Item "DEPLOYMENT.md" -Destination $serverDir
Copy-Item "README.md" -Destination $serverDir
Copy-Item ".python-version" -Destination $serverDir

# Check for Data
if (Test-Path "data\offline_index.sqlite") {
    Write-Host "Found index, copying..."
    New-Item -ItemType Directory -Path "$serverDir\data" -Force
    Copy-Item "data\offline_index.sqlite" -Destination "$serverDir\data"
} else {
    Write-Warning "offline_index.sqlite not found. You will need to build it on the target machine."
}

# 3. Package Client Components
Write-Host "Packaging Client..."
Copy-Item "client_mcp_adapter.py" -Destination $clientDir
Copy-Item "requirements.txt" -Destination $clientDir
Copy-Item "README.md" -Destination $clientDir
Copy-Item ".python-version" -Destination $clientDir

# 4. Attempt to Copy External Dependencies (Kiwix)
# Helper to copy external tools if they exist at known locations
$kiwixPath = "D:\Downloads\kiwix-tools_win-i686-3.7.0-2"
$libraryPath = "D:\Downloads\library.xml"

if (Test-Path $kiwixPath) {
    Write-Host "Copying Kiwix Tools from $kiwixPath..."
    Copy-Item $kiwixPath -Destination "$serverDir\kiwix-tools" -Recurse
} else {
    Write-Warning "Kiwix Tools not found at $kiwixPath. Please copy them manually to dist/server/kiwix-tools."
}

if (Test-Path $libraryPath) {
    Write-Host "Copying library.xml..."
    Copy-Item $libraryPath -Destination "$serverDir\library.xml"
} else {
    Write-Warning "library.xml not found at $libraryPath. Please copy it manually to dist/server/."
}

# 5. Create a Start Script for Server (Helper)
$serverStartScript = @"
@echo off
echo Starting Kiwix Serve...
start "Kiwix Serve" "kiwix-tools\kiwix-serve.exe" --port 8081 --library library.xml

echo Starting Search Server...
python search_server.py
"@
Set-Content -Path "$serverDir\start_server.bat" -Value $serverStartScript

Write-Host "`nPackaging Complete!"
Write-Host "Server package: $serverDir"
Write-Host "Client package: $clientDir"
