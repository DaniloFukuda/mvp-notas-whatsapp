$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

$logDir = "logs"
$logFile = Join-Path $logDir "viratexto_test_log.jsonl"

if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

if (-not (Test-Path -LiteralPath $logFile)) {
    New-Item -ItemType File -Force -Path $logFile | Out-Null
}

Write-Host "Acompanhando respostas do ViraTexto em $logFile"
Write-Host "Pressione Ctrl+C para parar."
Get-Content -LiteralPath $logFile -Wait
