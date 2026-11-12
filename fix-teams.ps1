<#
fix-teams.ps1 - Safe fixer for NEW Microsoft Teams (ms-teams.exe) on Windows.

Usage (PowerShell):
  .\fix-teams.ps1 -Level 1     # Close Teams, wait, reopen
  .\fix-teams.ps1 -Level 2     # Close Teams, back up + clear local cache, reopen

Safety rules:
  - Never touches chats. Messages live on Microsoft's servers, not in the local cache.
  - Only touches the Teams cache folder below. Nothing else.
  - Cache is MOVED to a timestamped backup, not deleted, so you can undo.
  - Every action is logged to teams_fix_log.txt next to this script.
  - Stops and logs if Teams will not close or the cache path looks wrong.
#>
param(
    [ValidateSet(1,2)]
    [int]$Level = 1
)

$ErrorActionPreference = "Stop"
$LogFile   = Join-Path $PSScriptRoot "teams_fix_log.txt"
$CachePath = Join-Path $env:LOCALAPPDATA "Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams"

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

Log "=== Run started. Level = $Level ==="

# --- Step 1: Close Teams completely ---
$procs = Get-Process -Name "ms-teams" -ErrorAction SilentlyContinue
if ($procs) {
    Log "Found $($procs.Count) ms-teams process(es). Closing..."
    $procs | ForEach-Object { try { $_.CloseMainWindow() | Out-Null } catch {} }
    Start-Sleep -Seconds 5
    Get-Process -Name "ms-teams" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
} else {
    Log "Teams was not running."
}

if (Get-Process -Name "ms-teams" -ErrorAction SilentlyContinue) {
    Log "ERROR: Teams is still running after close attempt. Stopping. Nothing was changed."
    exit 1
}
Log "Teams is fully closed."

# --- Step 2 (Level 2 only): back up and clear cache ---
if ($Level -ge 2) {
    # Safety check: path must exist and end exactly with the expected Teams folder
    if (-not (Test-Path $CachePath) -or -not $CachePath.EndsWith("LocalCache\Microsoft\MSTeams")) {
        Log "ERROR: Cache path not found or unexpected: $CachePath. Stopping. Nothing was changed."
        exit 1
    }
    $stamp  = Get-Date -Format "yyyyMMdd_HHmmss"
    $backup = "$CachePath`_backup_$stamp"
    Log "Moving cache to backup: $backup"
    Move-Item -Path $CachePath -Destination $backup
    Log "Cache moved. Teams will rebuild it on next launch. Backup can be deleted once Teams works."
}

# --- Step 3: Reopen Teams ---
Log "Reopening Teams..."
try {
    Start-Process "ms-teams:"
} catch {
    Log "ms-teams: link failed, trying app folder launch."
    Start-Process "explorer.exe" "shell:AppsFolder\MSTeams_8wekyb3d8bbwe!MSTeams"
}
Start-Sleep -Seconds 10

if (Get-Process -Name "ms-teams" -ErrorAction SilentlyContinue) {
    Log "Teams is running again."
} else {
    Log "WARNING: Teams did not appear to start. Try Level 2, or repair the app in Settings > Apps > Installed apps > Microsoft Teams > Advanced options > Repair."
}

Log "=== Run finished ==="