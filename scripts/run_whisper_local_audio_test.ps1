<#
.SYNOPSIS
Transcreve um audio ficticio localmente com Whisper, sem WhatsApp, Meta API ou servidor.

.PARAMETER Audio
Caminho do arquivo de audio ficticio.

.PARAMETER Model
Modelo Whisper. Default: tiny.

.PARAMETER Language
Idioma da transcricao. Default: pt.

.PARAMETER Output
Arquivo .txt para salvar a transcricao. Default: output/transcricao_teste.txt.

.PARAMETER KeepAudio
Parametro de compatibilidade repassado ao script Python.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$Audio,

    [string]$Model = "tiny",
    [string]$Language = "pt",
    [string]$Output = "output/transcricao_teste.txt",
    [switch]$KeepAudio
)

$ErrorActionPreference = "Stop"
$MaxAudioBytes = 25MB
$AllowedExtensions = @(".ogg", ".opus", ".mp3", ".m4a", ".wav")

function Test-CommandAvailable {
    param([Parameter(Mandatory=$true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Path -LiteralPath $Audio -PathType Leaf)) {
    Write-Error "Arquivo de audio nao encontrado: $Audio"
    exit 1
}

$audioItem = Get-Item -LiteralPath $Audio
$extension = $audioItem.Extension.ToLowerInvariant()
if ($AllowedExtensions -notcontains $extension) {
    Write-Error "Extensao nao suportada: $extension. Use: $($AllowedExtensions -join ', ')"
    exit 1
}

if ($audioItem.Length -gt $MaxAudioBytes) {
    $sizeMb = [Math]::Round($audioItem.Length / 1MB, 2)
    Write-Error "Arquivo muito grande ($sizeMb MB). Use audio ficticio de ate 25 MB."
    exit 1
}

if (-not (Test-CommandAvailable "ffmpeg")) {
    Write-Error "ffmpeg nao encontrado no PATH. Instale com: winget install Gyan.FFmpeg"
    exit 1
}

Write-Host ""
Write-Host "AVISO DE PRIVACIDADE"
Write-Host "- Use apenas audio ficticio."
Write-Host "- Nao use cliente real."
Write-Host "- Nao use CPF, valor sensivel, nome completo, nem dados reais de fazenda ou obra."
Write-Host "- Este teste nao chama WhatsApp, nao chama Meta API e nao altera .env."
Write-Host ""

$confirmation = Read-Host "Digite TESTAR para transcrever este audio localmente"
if ($confirmation -ne "TESTAR") {
    Write-Host "Transcricao cancelada."
    exit 0
}

$arguments = @(
    "scripts/test_whisper_transcricao.py",
    "--audio", $audioItem.FullName,
    "--model", $Model,
    "--language", $Language
)

$outputPath = $Output.Trim()
if ($outputPath) {
    $arguments += @("--output", $outputPath)
}

if ($KeepAudio) {
    $arguments += "--keep-audio"
}

$exitCode = 0
python @arguments
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0 -and $outputPath -and (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    Write-Host ""
    Write-Host "Transcricao salva em: $outputPath"
    Write-Host "Conteudo:"
    Get-Content -LiteralPath $outputPath
}

exit $exitCode
