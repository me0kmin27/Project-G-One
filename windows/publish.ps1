$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "GOne.Client\GOne.Client.csproj"
$output = Join-Path $PSScriptRoot "dist\win-x64"
$installerProject = Join-Path $PSScriptRoot "GOne.Installer\GOne.Installer.wixproj"
$wireGuardInstaller = Join-Path $output "wireguard-installer.exe"

Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue
dotnet publish $project -c Release -o $output
Invoke-WebRequest `
    -Uri "https://download.wireguard.com/windows-client/wireguard-installer.exe" `
    -OutFile $wireGuardInstaller
dotnet build $installerProject -c Release `
    -p:PublishDir=$output `
    -p:WireGuardInstaller=$wireGuardInstaller `
    -p:OutputPath=$output

if (-not (Test-Path (Join-Path $output "GOne.Client.msi"))) {
    throw "GOne.Client.msi was not produced"
}
Write-Host "Ready-to-install package: $output\GOne.Client.msi"
