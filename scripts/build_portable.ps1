param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$ProductName = "Voxa"
$PackageName = "Voxa-portable"

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

$TargetExe = Join-Path $Root "dist\$ProductName\$ProductName.exe"
Get-Process | Where-Object {
    try { $_.Path -eq $TargetExe -or $_.Path -like (Join-Path $Root "dist\$ProductName\*") } catch { $false }
} | Stop-Process -Force
Start-Sleep -Milliseconds 500

$TargetDir = Join-Path $Root "dist\$ProductName"
if (Test-Path $TargetDir) {
    Remove-Item -LiteralPath $TargetDir -Recurse -Force
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $ProductName `
    --icon $iconPath `
    --paths "src" `
    "launcher.py"

$PackageDir = Join-Path $Root "dist\$PackageName"
if (Test-Path $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageDir | Out-Null
Copy-Item -Path (Join-Path $TargetDir "*") -Destination $PackageDir -Recurse -Force
Copy-Item -LiteralPath "README.md" -Destination (Join-Path $PackageDir "README.md")
Get-Content -LiteralPath "scripts\install_desktop.ps1" -Raw |
    Set-Content -LiteralPath (Join-Path $PackageDir "Установить на рабочий стол.ps1") -Encoding UTF8

$Bat = @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Установить на рабочий стол.ps1"
pause
"@
$Bat | Set-Content -Path (Join-Path $PackageDir "Install.bat") -Encoding ASCII

$ReadmeTxt = @"
Voxa

1. Не вытаскивайте "Voxa.exe" отдельно: рядом нужна папка "_internal".
2. Запустите "Install.bat" для установки или "Voxa.exe" как переносимую версию.
3. Маленькая кнопка появится на экране, иконка - возле часов.
4. Горячая клавиша: F8.
5. Первый запуск может подготовить бесплатную локальную модель.
"@
$ReadmeTxt | Set-Content -Path (Join-Path $PackageDir "Прочитай меня.txt") -Encoding UTF8

$ZipPath = Join-Path $Root "dist\$PackageName.zip"
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath
Write-Host "Готово: $ZipPath"
