$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "GOne.Client\GOne.Client.csproj"
$output = Join-Path $PSScriptRoot "dist\win-x64"

Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue
dotnet publish $project -c Release -o $output

Write-Host "Ready-to-test executable: $output\GOne.Client.exe"
