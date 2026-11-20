<#
.SYNOPSIS
    Install or uninstall Govee autostart scheduled tasks for the current user.

.DESCRIPTION
    Registers two scheduled tasks that run weather_sync.py and game_sync.py
    at logon, hidden (via pythonw.exe). Tasks run for the current user only
    and do not require admin rights.

.PARAMETER Uninstall
    Remove the scheduled tasks instead of installing them.

.PARAMETER DryRun
    Print what would be done without actually registering or removing tasks.

.EXAMPLE
    .\install.ps1
    Installs both tasks.

.EXAMPLE
    .\install.ps1 -DryRun
    Shows what would be installed.

.EXAMPLE
    .\install.ps1 -Uninstall
    Removes both tasks.
#>

param(
    [switch]$Uninstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Resolve paths relative to this script
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Resolve pythonw.exe
try {
    $pythonw = (Get-Command pythonw.exe).Source
} catch {
    Write-Error "pythonw.exe not found in PATH. Install Python or add it to PATH."
    exit 1
}

$tasks = @(
    @{
        Name = "Govee weather sync"
        Script = "weather_sync.py"
        Description = "Run Govee weather sync at logon (hidden)"
    },
    @{
        Name = "Govee game sync"
        Script = "game_sync.py"
        Description = "Run Govee game sync at logon (hidden)"
    }
)

if ($Uninstall) {
    Write-Host "Uninstalling Govee autostart tasks..."
    foreach ($t in $tasks) {
        if ($DryRun) {
            Write-Host "[dry-run] Would remove task: $($t.Name)"
        } else {
            try {
                Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
                Write-Host "Removed task: $($t.Name)"
            } catch {
                Write-Host "Task not found (already removed?): $($t.Name)"
            }
        }
    }
    if ($DryRun) {
        Write-Host "[dry-run] Done (no changes made)."
    } else {
        Write-Host "Done."
    }
} else {
    Write-Host "Installing Govee autostart tasks..."

    # Build trigger: at logon for current user
    $trigger = New-ScheduledTaskTrigger -AtLogOn

    # Build settings: no time limit, restart on failure, don't start if running
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew

    foreach ($t in $tasks) {
        if ($DryRun) {
            Write-Host "[dry-run] Would register task: $($t.Name)"
            Write-Host "  Trigger: AtLogOn (current user)"
            Write-Host "  Execute: $pythonw"
            Write-Host "  Argument: $($t.Script)"
            Write-Host "  WorkingDirectory: $repoRoot"
            Write-Host "  Settings: no time limit, restart 3x on failure (1 min apart), ignore new instances"
        } else {
            $action = New-ScheduledTaskAction `
                -Execute $pythonw `
                -Argument $t.Script `
                -WorkingDirectory $repoRoot

            Register-ScheduledTask `
                -TaskName $t.Name `
                -Trigger $trigger `
                -Action $action `
                -Settings $settings `
                -Description $t.Description `
                -User (whoami) `
                -RunLevel Limited `
                -Force

            Write-Host "Registered task: $($t.Name)"
        }
    }

    if ($DryRun) {
        Write-Host "[dry-run] Done (no changes made)."
    } else {
        Write-Host "Done. Tasks will run at your next logon."
        Write-Host "To test now: Start-ScheduledTask -TaskName `"Govee weather sync`""
    }
}
