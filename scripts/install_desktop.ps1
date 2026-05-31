$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe = Join-Path $Here "Глас.exe"
if (!(Test-Path $SourceExe)) {
    $SourceExe = Join-Path $Here "Голосовой набор.exe"
}
if (!(Test-Path $SourceExe)) {
    throw "Не найден файл программы: $SourceExe"
}

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\GolosovoyNabor"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$Exe = Join-Path $InstallDir "Глас.exe"
$LegacyExe = Join-Path $InstallDir "Голосовой набор.exe"

Get-Process | Where-Object {
    try { $_.Path -eq $Exe -or $_.Path -eq $LegacyExe -or $_.Path -like (Join-Path $InstallDir "*") } catch { $false }
} | Stop-Process -Force
Start-Sleep -Milliseconds 500

foreach ($item in Get-ChildItem -LiteralPath $Here -Force) {
    if ($item.Name -in @("Install.bat", "Установить на рабочий стол.ps1")) {
        continue
    }
    Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $InstallDir $item.Name) -Recurse -Force
}
if (!(Test-Path $Exe) -and (Test-Path $LegacyExe)) {
    Copy-Item -LiteralPath $LegacyExe -Destination $Exe -Force
}
if ((Test-Path $LegacyExe) -and $LegacyExe -ne $Exe) {
    Remove-Item -LiteralPath $LegacyExe -Force
}

$Shell = New-Object -ComObject WScript.Shell

$Desktop = [Environment]::GetFolderPath("Desktop")
$DesktopShortcut = Join-Path $Desktop "Глас.lnk"
$Shortcut = $Shell.CreateShortcut($DesktopShortcut)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Бесплатная диктовка текста"
$Shortcut.Save()
$LegacyDesktopShortcut = Join-Path $Desktop "Голосовой набор.lnk"
if (Test-Path $LegacyDesktopShortcut) {
    try {
        $LegacyShortcut = $Shell.CreateShortcut($LegacyDesktopShortcut)
        if ($LegacyShortcut.TargetPath -eq $LegacyExe -or $LegacyShortcut.TargetPath -eq $Exe) {
            Remove-Item -LiteralPath $LegacyDesktopShortcut -Force
        }
    } catch {
    }
}

$StartMenuDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Глас"
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
$StartShortcut = Join-Path $StartMenuDir "Глас.lnk"
$Shortcut = $Shell.CreateShortcut($StartShortcut)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Бесплатная диктовка текста"
$Shortcut.Save()
$LegacyStartShortcut = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Голосовой набор\Голосовой набор.lnk"
if (Test-Path $LegacyStartShortcut) {
    try {
        $LegacyShortcut = $Shell.CreateShortcut($LegacyStartShortcut)
        if ($LegacyShortcut.TargetPath -eq $LegacyExe -or $LegacyShortcut.TargetPath -eq $Exe) {
            Remove-Item -LiteralPath $LegacyStartShortcut -Force
        }
    } catch {
    }
}

Write-Host "Программа установлена: $InstallDir"
Write-Host "Ярлык создан: $DesktopShortcut"
