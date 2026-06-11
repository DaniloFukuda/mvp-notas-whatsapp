param(
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackupDir = Join-Path $ProjectRoot "backups"
$DatabasePath = Join-Path $ProjectRoot "data\app.db"
$UploadsPath = Join-Path $ProjectRoot "data\documentos\uploads"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Warning "Pare o servidor local e confirme que nao ha mensagens chegando antes do backup final."
Write-Output "Projeto: Ciclus/RDV"
Write-Output "Banco: $DatabasePath"
Write-Output "Uploads: $UploadsPath"
Write-Output ".env nao sera copiado."

if ($WhatIf) {
    Write-Output "Modo WhatIf: nenhum arquivo sera criado."
    exit 0
}

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
$Artifacts = @()

if (Test-Path -LiteralPath $DatabasePath -PathType Leaf) {
    $DatabaseBackup = Join-Path $BackupDir "ciclus_app_pre_migracao_$Timestamp.db"
    Copy-Item -LiteralPath $DatabasePath -Destination $DatabaseBackup
    $Artifacts += Get-Item -LiteralPath $DatabaseBackup
}
else {
    Write-Warning "Banco nao encontrado; nenhum banco foi copiado."
}

if (Test-Path -LiteralPath $UploadsPath -PathType Container) {
    $UploadsBackup = Join-Path $BackupDir "ciclus_uploads_pre_migracao_$Timestamp.zip"
    Compress-Archive -LiteralPath $UploadsPath -DestinationPath $UploadsBackup
    $Artifacts += Get-Item -LiteralPath $UploadsBackup
}
else {
    Write-Warning "Diretorio de uploads nao encontrado; nenhum ZIP foi criado."
}

foreach ($Artifact in $Artifacts) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact.FullName).Hash
    $ZipFileCount = "-"
    if ($Artifact.Extension -eq ".zip") {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($Artifact.FullName)
        try {
            $ZipFileCount = @($Archive.Entries | Where-Object { $_.Name }).Count
        }
        finally {
            $Archive.Dispose()
        }
    }

    Write-Output "Artefato: $($Artifact.FullName)"
    Write-Output "TamanhoBytes: $($Artifact.Length)"
    Write-Output "SHA256: $Hash"
    Write-Output "ArquivosNoZip: $ZipFileCount"
}
