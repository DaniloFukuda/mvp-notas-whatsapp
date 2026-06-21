param(
    [int]$Port = 8000,
    [switch]$CheckOnly,
    [switch]$SendText
)

$ErrorActionPreference = "Stop"

function Import-DotEnvIfPresent {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Ensure-ViraTextoLogFile {
    $logDir = "logs"
    $logFile = Join-Path $logDir "viratexto_test_log.jsonl"

    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }

    if (-not (Test-Path -LiteralPath $logFile)) {
        New-Item -ItemType File -Force -Path $logFile | Out-Null
    }

    return $logFile
}

function Mask-Phone {
    param([string]$Phone)

    if (-not $Phone -or $Phone.Length -le 4) {
        return "***"
    }
    return "***$($Phone.Substring($Phone.Length - 4))"
}

function Test-Truthy {
    param([string]$Value)

    return @("1", "true", "yes", "sim", "on") -contains $Value.Trim().ToLowerInvariant()
}

function Test-InvalidViraTextoPhone {
    param([string]$Phone)

    $clean = $Phone.Trim()
    if (-not $clean) {
        return $true
    }
    if ($clean -in @("55DDDNUMERO", "55DDDNUMERO", "55XXXXXXXXXXX")) {
        return $true
    }
    if ($clean -match "[A-Za-zXx]") {
        return $true
    }
    if ($clean -notmatch "^\d+$") {
        return $true
    }
    if ($clean.Length -lt 12) {
        return $true
    }
    return $false
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
Import-DotEnvIfPresent -Path (Join-Path $repoRoot ".env")

$logFile = Ensure-ViraTextoLogFile
$serverCommand = "python -m uvicorn web_upload:app --reload --host 127.0.0.1 --port $Port"
$watchCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_viratexto_log.ps1"
$ngrokCommand = "ngrok http $Port"
$sendCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_viratexto_text_test.ps1 -SendReal"

Write-Host "POC local ViraTexto + webhook + ngrok"
Write-Host ""
Write-Host "Objetivo:"
Write-Host "- validar se o webhook local recebe a resposta do ViraTexto;"
Write-Host "- lembrar que a Meta precisa apontar temporariamente para a URL do ngrok;"
Write-Host "- nao enviar audio ainda."
Write-Host ""

$tokenPresent = -not [string]::IsNullOrWhiteSpace($env:WHATSAPP_TOKEN) -or -not [string]::IsNullOrWhiteSpace($env:WHATSAPP_ACCESS_TOKEN)
$phoneNumberIdPresent = -not [string]::IsNullOrWhiteSpace($env:WHATSAPP_PHONE_NUMBER_ID)
$viratextoPhone = [string]$env:VIRATEXTO_PHONE
$testModeActive = Test-Truthy -Value ([string]$env:VIRATEXTO_TEST_MODE)

Write-Host "Log preparado em: $logFile"
Write-Host "Destino ViraTexto: $(Mask-Phone -Phone $viratextoPhone)"
Write-Host "VIRATEXTO_TEST_MODE ativo: $testModeActive"
Write-Host ""

if (-not $phoneNumberIdPresent) {
    Write-Error "Variavel obrigatoria ausente: WHATSAPP_PHONE_NUMBER_ID."
    exit 1
}

if (-not $tokenPresent) {
    Write-Error "Token ausente. Configure WHATSAPP_TOKEN ou WHATSAPP_ACCESS_TOKEN. O token nao sera impresso."
    exit 1
}

if (Test-InvalidViraTextoPhone -Phone $viratextoPhone) {
    Write-Error "VIRATEXTO_PHONE invalido. Configure um numero real no formato 55DDDNUMERO, sem placeholders."
    exit 1
}

if (-not $testModeActive) {
    Write-Error "VIRATEXTO_TEST_MODE precisa estar true para esta POC local interceptar a resposta como teste."
    exit 1
}

Write-Host "Checando servidor local na porta $Port..."
& powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\check_local_webhook.ps1" -Port $Port
$webhookCheckExitCode = $LASTEXITCODE

if ($webhookCheckExitCode -ne 0) {
    Write-Host ""
    Write-Host "Servidor local nao parece estar rodando."
    Write-Host "Suba em outro terminal:"
    Write-Host $serverCommand
    exit $webhookCheckExitCode
}

Write-Host ""
Write-Host "Abra o watcher do log em outro terminal:"
Write-Host $watchCommand
Write-Host ""
Write-Host "Abra o ngrok em outro terminal:"
Write-Host $ngrokCommand
Write-Host ""

if ($CheckOnly) {
    Write-Host "CheckOnly ativo: checagem concluida sem pedir URL do ngrok e sem envio."
    exit 0
}

$ngrokUrl = Read-Host "Cole a URL publica HTTPS do ngrok, exemplo https://abc123.ngrok-free.app"
$ngrokUrl = $ngrokUrl.Trim().TrimEnd("/")
if (-not $ngrokUrl -or $ngrokUrl -notmatch "^https://") {
    Write-Error "URL do ngrok invalida. Use uma URL HTTPS, por exemplo https://abc123.ngrok-free.app."
    exit 1
}

$callbackUrl = "$ngrokUrl/webhook/whatsapp"
Write-Host ""
Write-Host "Configure esta URL temporariamente na Meta:"
Write-Host $callbackUrl
Write-Host ""
Write-Host "Depois volte aqui."
$ready = Read-Host "Digite PRONTO para continuar"
if ($ready -ne "PRONTO") {
    Write-Host "Encerrado sem enviar nada."
    exit 0
}

if ($SendText) {
    Write-Host ""
    Write-Host "Iniciando script de envio real de texto. Ele ainda pedira ENVIAR."
    & powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_viratexto_text_test.ps1" -SendReal
    $sendExitCode = $LASTEXITCODE
} else {
    Write-Host ""
    Write-Host "Para fazer o envio real de texto depois, rode:"
    Write-Host $sendCommand
    $sendExitCode = 0
}

Write-Host ""
Write-Host "Depois do teste:"
Write-Host "- confira logs\viratexto_test_log.jsonl;"
Write-Host "- restaure o webhook original da Meta;"
Write-Host "- nao envie audio ate a resposta de texto aparecer no log."

exit $sendExitCode
