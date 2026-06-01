$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe = Join-Path $Here "Voxa.exe"
if (!(Test-Path $SourceExe)) {
    $SourceExe = Join-Path $Here "Глас.exe"
}
if (!(Test-Path $SourceExe)) {
    $SourceExe = Join-Path $Here "Голосовой набор.exe"
}
if (!(Test-Path $SourceExe)) {
    throw "Не найден файл программы: $SourceExe"
}

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\GolosovoyNabor"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$Exe = Join-Path $InstallDir "Voxa.exe"
$GlasExe = Join-Path $InstallDir "Глас.exe"
$LegacyExe = Join-Path $InstallDir "Голосовой набор.exe"

Get-Process | Where-Object {
    try { $_.Path -eq $Exe -or $_.Path -eq $GlasExe -or $_.Path -eq $LegacyExe -or $_.Path -like (Join-Path $InstallDir "*") } catch { $false }
} | Stop-Process -Force
Start-Sleep -Milliseconds 500

foreach ($item in Get-ChildItem -LiteralPath $Here -Force) {
    if ($item.Name -in @("Install.bat", "Установить на рабочий стол.ps1")) {
        continue
    }
    $DestinationPath = Join-Path $InstallDir $item.Name
    if (Test-Path $DestinationPath) {
        Remove-Item -LiteralPath $DestinationPath -Recurse -Force
    }
    Copy-Item -LiteralPath $item.FullName -Destination $DestinationPath -Recurse -Force
}
if (!(Test-Path $Exe) -and (Test-Path $LegacyExe)) {
    Copy-Item -LiteralPath $LegacyExe -Destination $Exe -Force
}
if (!(Test-Path $Exe) -and (Test-Path $GlasExe)) {
    Copy-Item -LiteralPath $GlasExe -Destination $Exe -Force
}
if ((Test-Path $GlasExe) -and $GlasExe -ne $Exe) {
    Remove-Item -LiteralPath $GlasExe -Force
}
if ((Test-Path $LegacyExe) -and $LegacyExe -ne $Exe) {
    Remove-Item -LiteralPath $LegacyExe -Force
}

$Shell = New-Object -ComObject WScript.Shell

$Desktop = [Environment]::GetFolderPath("Desktop")
$DesktopShortcut = Join-Path $Desktop "Voxa.lnk"
$Shortcut = $Shell.CreateShortcut($DesktopShortcut)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Бесплатная диктовка текста"
$Shortcut.Save()
$GlasDesktopShortcut = Join-Path $Desktop "Глас.lnk"
if (Test-Path $GlasDesktopShortcut) {
    try {
        $GlasShortcut = $Shell.CreateShortcut($GlasDesktopShortcut)
        if ($GlasShortcut.TargetPath -eq $GlasExe -or $GlasShortcut.TargetPath -eq $Exe) {
            Remove-Item -LiteralPath $GlasDesktopShortcut -Force
        }
    } catch {
    }
}
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

$StartMenuDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Voxa"
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
$StartShortcut = Join-Path $StartMenuDir "Voxa.lnk"
$Shortcut = $Shell.CreateShortcut($StartShortcut)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Бесплатная диктовка текста"
$Shortcut.Save()
$GlasStartShortcut = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Глас\Глас.lnk"
if (Test-Path $GlasStartShortcut) {
    try {
        $GlasShortcut = $Shell.CreateShortcut($GlasStartShortcut)
        if ($GlasShortcut.TargetPath -eq $GlasExe -or $GlasShortcut.TargetPath -eq $Exe) {
            Remove-Item -LiteralPath $GlasStartShortcut -Force
        }
    } catch {
    }
}
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
