$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackupDir = Join-Path $ProjectRoot "backups"
$DatabasePath = Join-Path $ProjectRoot "data\app.db"
$UploadsPath = Join-Path $ProjectRoot "data\documentos\uploads"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$CreatedPaths = @()

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

if (Test-Path -LiteralPath $DatabasePath -PathType Leaf) {
    $DatabaseBackup = Join-Path $BackupDir "ciclus_app_$Timestamp.db"
    Copy-Item -LiteralPath $DatabasePath -Destination $DatabaseBackup
    $CreatedPaths += $DatabaseBackup
}

if (Test-Path -LiteralPath $UploadsPath -PathType Container) {
    $UploadsBackup = Join-Path $BackupDir "ciclus_uploads_$Timestamp.zip"
    Compress-Archive -LiteralPath $UploadsPath -DestinationPath $UploadsBackup
    $CreatedPaths += $UploadsBackup
}

$CreatedPaths | ForEach-Object { Write-Output $_ }
