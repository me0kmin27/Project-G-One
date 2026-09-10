$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "GOne.Client\GOne.Client.csproj"
$output = Join-Path $PSScriptRoot "dist\win-x64"

Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue
dotnet publish $project -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o $output

Write-Host "Ready-to-test executable: $output\GOne.Client.exe"
