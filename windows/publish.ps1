$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "GOne.Client\GOne.Client.csproj"
$output = Join-Path $PSScriptRoot "dist\win-x64"

Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue
dotnet publish $project -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o $output

if ($LASTEXITCODE -ne 0) {
  throw "dotnet publish failed with exit code $LASTEXITCODE"
}

$executable = Join-Path $output "GOne.Client.exe"
$settings = Join-Path $output "clientsettings.json"
if (-not (Test-Path $executable -PathType Leaf)) {
  throw "Publish completed without GOne.Client.exe"
}
if (-not (Test-Path $settings -PathType Leaf)) {
  throw "Publish completed without clientsettings.json"
}

Write-Host "Ready-to-test executable: $executable"
