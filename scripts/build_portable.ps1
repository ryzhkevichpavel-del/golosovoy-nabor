param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path $Python)) {
    py -3.11 -m venv .venv
    $Python = ".\.venv\Scripts\python.exe"
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-dev.txt
& $Python -m pytest

$iconPath = Join-Path $Root "assets\app.ico"
if (!(Test-Path $iconPath)) {
    & $Python scripts\make_icon.py
}

$TargetExe = Join-Path $Root "dist\Голосовой набор.exe"
Get-Process | Where-Object {
    try { $_.Path -eq $TargetExe } catch { $false }
} | Stop-Process -Force
Start-Sleep -Milliseconds 500

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "Голосовой набор" `
    --icon $iconPath `
    --paths "src" `
    "launcher.py"

$PackageDir = Join-Path $Root "dist\GolosovoyNabor-portable"
if (Test-Path $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageDir | Out-Null
Copy-Item -LiteralPath "dist\Голосовой набор.exe" -Destination $PackageDir
Copy-Item -LiteralPath "README.md" -Destination (Join-Path $PackageDir "README.md")
Get-Content -LiteralPath "scripts\install_desktop.ps1" -Raw |
    Set-Content -LiteralPath (Join-Path $PackageDir "Установить на рабочий стол.ps1") -Encoding utf8BOM

$Bat = @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Установить на рабочий стол.ps1"
pause
"@
$Bat | Set-Content -Path (Join-Path $PackageDir "Install.bat") -Encoding ASCII

$ReadmeTxt = @"
Голосовой набор

1. Запустите файл "Голосовой набор.exe".
2. Иконка появится возле часов.
3. Горячая клавиша: Ctrl + Alt + Space.
4. Первый запуск может скачать бесплатный локальный Whisper.
"@
$ReadmeTxt | Set-Content -Path (Join-Path $PackageDir "Прочитай меня.txt") -Encoding UTF8

$ZipPath = Join-Path $Root "dist\GolosovoyNabor-portable.zip"
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath
Write-Host "Готово: $ZipPath"
