<#
.SYNOPSIS
Prepara o ambiente local para testar Whisper sem WhatsApp, Meta API ou servidor.

.PARAMETER SkipInstall
Quando informado, apenas verifica Python e ffmpeg, sem instalar dependencias.
#>
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailable {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "Verificando Python..."
if (-not (Test-CommandAvailable "python")) {
    Write-Error "Python nao encontrado no PATH. Instale Python e reabra o terminal."
    exit 1
}

python --version

Write-Host "Verificando ffmpeg..."
if (-not (Test-CommandAvailable "ffmpeg")) {
    Write-Warning "ffmpeg nao encontrado no PATH."
    Write-Host "Para instalar no Windows, execute:"
    Write-Host "winget install Gyan.FFmpeg"
    Write-Host "Depois reabra o terminal e rode este script novamente."
} else {
    ffmpeg -version | Select-Object -First 1
}

if ($SkipInstall) {
    Write-Host "SkipInstall informado: dependencias nao serao instaladas."
    exit 0
}

Write-Host "Instalando dependencias de transcricao..."
python -m pip install -r requirements-transcription.txt

Write-Host "Setup local concluido."
Write-Host "Este script nao altera .env, nao ativa feature flag e nao chama WhatsApp/Meta."
