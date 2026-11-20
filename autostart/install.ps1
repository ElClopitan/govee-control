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

.PARAMETER NoStart
    Register the tasks but do not start them immediately.

.EXAMPLE
    .\install.ps1
    Installs both tasks and starts them.

.EXAMPLE
    .\install.ps1 -DryRun
    Shows what would be installed.

.EXAMPLE
    .\install.ps1 -Uninstall
    Removes both tasks.
#>

param(
    [switch]$Uninstall,
    [switch]$DryRun,
    [switch]$NoStart
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

# Current user for the trigger and registration
$user = whoami

$tasks = @(
    @{
        Name = "Govee weather sync"
        Script = "weather_sync.py"
        LogFile = "state\weather_sync.log"
        Description = "Run Govee weather sync at logon (hidden)"
    },
    @{
        Name = "Govee game sync"
        Script = "game_sync.py"
        LogFile = "state\game_sync.log"
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
                Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
            } catch {
                # Task may not be running; ignore
            }
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

    # Ensure state directory exists for log files
    if (-not $DryRun) {
        $stateDir = Join-Path $repoRoot "state"
        if (-not (Test-Path $stateDir)) {
            New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
            Write-Host "Created state directory: $stateDir"
        }
    }

    # Build trigger: at logon for current user
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user

    # Build settings: no time limit, restart on failure, don't start if running
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew

    $anyFailed = $false

    foreach ($t in $tasks) {
        $arg = "$($t.Script) --log-file $($t.LogFile)"
        if ($DryRun) {
            Write-Host "[dry-run] Would register task: $($t.Name)"
            Write-Host "  Trigger: AtLogOn, user $user"
            Write-Host "  Execute: $pythonw"
            Write-Host "  Argument: $arg"
            Write-Host "  WorkingDirectory: $repoRoot"
            Write-Host "  Settings: no time limit, restart 3x on failure (1 min apart), ignore new instances"
            if (-not $NoStart) {
                Write-Host "  Would start task immediately after registration"
            }
        } else {
            try {
                $action = New-ScheduledTaskAction `
                    -Execute $pythonw `
                    -Argument $arg `
                    -WorkingDirectory $repoRoot

                Register-ScheduledTask `
                    -TaskName $t.Name `
                    -Trigger $trigger `
                    -Action $action `
                    -Settings $settings `
                    -Description $t.Description `
                    -User $user `
                    -RunLevel Limited `
                    -Force

                Write-Host "Registered task: $($t.Name)"

                if (-not $NoStart) {
                    Start-ScheduledTask -TaskName $t.Name
                    Write-Host "Started task: $($t.Name)"
                }
            } catch {
                Write-Host "ERROR: could not register `"$($t.Name)`": $($_.Exception.Message)" -ForegroundColor Red
                $anyFailed = $true
            }
        }
    }

    if ($DryRun) {
        Write-Host "[dry-run] Done (no changes made)."
    } else {
        if ($anyFailed) {
            Write-Host "Some tasks failed to register. Check the errors above." -ForegroundColor Red
            exit 1
        }
        if ($NoStart) {
            Write-Host "Done. Tasks will run at your next logon."
        } else {
            Write-Host "Done. Tasks are running now and will run at each logon."
            Write-Host "To check status: Get-ScheduledTask -TaskName 'Govee*' | Format-Table TaskName, State"
        }
    }
}
