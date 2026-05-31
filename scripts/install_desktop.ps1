$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe = Join-Path $Here "Голосовой набор.exe"
if (!(Test-Path $SourceExe)) {
    throw "Не найден файл программы: $SourceExe"
}

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\GolosovoyNabor"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Copy-Item -LiteralPath $SourceExe -Destination (Join-Path $InstallDir "Голосовой набор.exe") -Force
foreach ($name in @("README.md", "Прочитай меня.txt")) {
    $source = Join-Path $Here $name
    if (Test-Path $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $InstallDir $name) -Force
    }
}

$Exe = Join-Path $InstallDir "Голосовой набор.exe"
$Shell = New-Object -ComObject WScript.Shell

$Desktop = [Environment]::GetFolderPath("Desktop")
$DesktopShortcut = Join-Path $Desktop "Голосовой набор.lnk"
$Shortcut = $Shell.CreateShortcut($DesktopShortcut)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Бесплатный голосовой набор текста"
$Shortcut.Save()

$StartMenuDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Голосовой набор"
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
$StartShortcut = Join-Path $StartMenuDir "Голосовой набор.lnk"
$Shortcut = $Shell.CreateShortcut($StartShortcut)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Бесплатный голосовой набор текста"
$Shortcut.Save()

Write-Host "Программа установлена: $InstallDir"
Write-Host "Ярлык создан: $DesktopShortcut"
