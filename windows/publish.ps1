$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "GOne.Client\GOne.Client.csproj"
$installerProject = Join-Path $PSScriptRoot "GOne.Installer\GOne.Installer.wixproj"
$dist = Join-Path $PSScriptRoot "dist"
$publishOutput = Join-Path $dist "publish"
$wireGuardOutput = Join-Path $dist "wireguard"
$wireGuardAdministrativeImage = Join-Path $dist "wireguard-image"
$packageOutput = Join-Path $dist "win-x64"
$wireGuardMsi = Join-Path $dist "wireguard-amd64-0.5.3.msi"

Remove-Item $dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item $wireGuardOutput -ItemType Directory -Force | Out-Null

Write-Host "Publishing the self-contained Windows client..."
dotnet publish $project -c Release -o $publishOutput

Write-Host "Downloading the pinned official WireGuard runtime package..."
Invoke-WebRequest `
    -Uri "https://download.wireguard.com/windows-client/wireguard-amd64-0.5.3.msi" `
    -OutFile $wireGuardMsi

# Create an administrative image instead of running WireGuard's installer on
# either the build host or the user's PC. Only the runtime executables are then
# packaged inside G-One's own installation directory.
$extract = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
    "/a", "`"$wireGuardMsi`"", "/qn", "TARGETDIR=`"$wireGuardAdministrativeImage`""
)
if ($extract.ExitCode -ne 0) {
    throw "Unable to extract the WireGuard runtime (msiexec exit code $($extract.ExitCode))."
}

$wireGuardExe = Get-ChildItem $wireGuardAdministrativeImage -Filter wireguard.exe -Recurse | Select-Object -First 1
$wgExe = Get-ChildItem $wireGuardAdministrativeImage -Filter wg.exe -Recurse | Select-Object -First 1
if (-not $wireGuardExe -or -not $wgExe) {
    throw "The official WireGuard package did not contain the expected runtime files."
}
Copy-Item $wireGuardExe.FullName (Join-Path $wireGuardOutput "wireguard.exe")
Copy-Item $wgExe.FullName (Join-Path $wireGuardOutput "wg.exe")

Write-Host "Building the all-in-one MSI package..."
dotnet build $installerProject -c Release `
    -p:PublishDir="$publishOutput" `
    -p:WireGuardRuntimeDir="$wireGuardOutput" `
    -p:OutputPath="$packageOutput"

$msi = Join-Path $packageOutput "GOne.Client-x64.msi"
if (-not (Test-Path $msi)) {
    throw "MSI package was not produced: $msi"
}
Write-Host "Ready-to-install package: $msi"
