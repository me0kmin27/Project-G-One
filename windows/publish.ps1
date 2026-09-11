$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "GOne.Client\GOne.Client.csproj"
$installerProject = Join-Path $PSScriptRoot "GOne.Installer\GOne.Installer.wixproj"
$dist = Join-Path $PSScriptRoot "dist"
$publishOutput = Join-Path $dist "publish"
$dependencyOutput = Join-Path $dist "dependencies"
$packageOutput = Join-Path $dist "win-x64"
$wireGuardInstaller = Join-Path $dependencyOutput "wireguard-installer.exe"

Remove-Item $dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item $dependencyOutput -ItemType Directory -Force | Out-Null

Write-Host "Publishing the self-contained Windows client..."
dotnet publish $project -c Release -o $publishOutput

Write-Host "Downloading the official WireGuard runtime installer..."
Invoke-WebRequest `
    -Uri "https://download.wireguard.com/windows-client/wireguard-installer.exe" `
    -OutFile $wireGuardInstaller

Write-Host "Building the all-in-one MSI package..."
dotnet build $installerProject -c Release `
    -p:PublishDir="$publishOutput" `
    -p:WireGuardInstaller="$wireGuardInstaller" `
    -p:OutputPath="$packageOutput"

$msi = Join-Path $packageOutput "GOne.Client-x64.msi"
if (-not (Test-Path $msi)) {
    throw "MSI package was not produced: $msi"
}
Write-Host "Ready-to-install package: $msi"
