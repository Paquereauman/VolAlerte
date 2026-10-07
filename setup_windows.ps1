# Script de configuration du raccourci Bureau et de la tâche planifiée Windows
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Raccourci Bureau
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop "VolAlerte.lnk"
$vbsPath = Join-Path $scriptDir "launch_app.vbs"
$iconPath = Join-Path $scriptDir "app_icon.ico"

$s = $ws.CreateShortcut($shortcutPath)
$s.TargetPath = "wscript.exe"
$s.Arguments = "`"$vbsPath`""
$s.WorkingDirectory = $scriptDir
$s.IconLocation = $iconPath
$s.Description = "VolAlerte - Suivi des Prix de Vols"
$s.Save()
Write-Host "Raccourci Bureau créé : $shortcutPath"

# 2. Tâche planifiée Windows (avec rattrapage après démarrage manqué)
$pythonw = Join-Path $scriptDir "venv\Scripts\pythonw.exe"
$trackerScript = Join-Path $scriptDir "run_tracker.py"

try {
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$trackerScript`"" -WorkingDirectory $scriptDir
    $trigger = New-ScheduledTaskTrigger -Daily -At 09:00
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "VolAlerte_DailyCheck" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Tâche planifiée 'VolAlerte_DailyCheck' enregistrée avec succès."
} catch {
    Write-Host "Utilisation de schtasks comme fallback..."
    schtasks /create /tn "VolAlerte_DailyCheck" /tr "`"$pythonw`" `"$trackerScript`"" /sc daily /st 09:00 /f | Out-Null
}
