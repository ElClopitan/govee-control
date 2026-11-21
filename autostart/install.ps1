<#
.SYNOPSIS
    Install or uninstall Govee autostart scheduled tasks for the current user.

.DESCRIPTION
    Registers three scheduled tasks that run weather_sync.py, game_sync.py,
    and tray.py at logon, hidden (via pythonw.exe). Tasks run for the current
    user only and do not require admin rights.

.PARAMETER Uninstall
    Remove the scheduled tasks instead of installing them.

.PARAMETER DryRun
    Print what would be done without actually registering or removing tasks.

.PARAMETER NoStart
    Register the tasks but do not start them immediately.

.PARAMETER PythonW
    Path to pythonw.exe to use. If not given, the first pythonw.exe on PATH
    is used. If the resolved path is the Microsoft Store stub
    (...\\WindowsApps\\pythonw.exe), a warning is printed.

.EXAMPLE
    .\install.ps1
    Installs all three tasks and starts them.

.EXAMPLE
    .\install.ps1 -DryRun
    Shows what would be installed.

.EXAMPLE
    .\install.ps1 -Uninstall
    Removes all three tasks.

.EXAMPLE
    .\install.ps1 -PythonW C:\Python312\pythonw.exe
    Installs using a specific pythonw.exe.
#>

param(
    [switch]$Uninstall,
    [switch]$DryRun,
    [switch]$NoStart,
    [string]$PythonW
)

$ErrorActionPreference = "Stop"

# Resolve paths relative to this script
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Resolve pythonw.exe
if ($PythonW) {
    if (-not (Test-Path $PythonW)) {
        Write-Error "pythonw.exe not found at specified path: $PythonW"
        exit 1
    }
    $pythonw = $PythonW
} else {
    try {
        $pythonw = (Get-Command pythonw.exe).Source
    } catch {
        Write-Error "pythonw.exe not found in PATH. Install Python or add it to PATH."
        exit 1
    }
}

if ($pythonw -like "*\WindowsApps\*") {
    Write-Warning ("pythonw.exe resolved to the Microsoft Store stub ($pythonw). " +
        "This may not work from Task Scheduler. Consider using -PythonW to specify " +
        "the real Python installation.")
}

Write-Host "Using pythonw: $pythonw"

# Current user for the trigger and registration
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$tasks = @(
    @{
        Name = "Govee weather sync"
        Script = "weather_sync.py"
        Arguments = "--log-file state\weather_sync.log"
        Description = "Run Govee weather sync at logon (hidden)"
    },
    @{
        Name = "Govee game sync"
        Script = "game_sync.py"
        Arguments = "--log-file state\game_sync.log"
        Description = "Run Govee game sync at logon (hidden)"
    },
    @{
        Name = "Govee tray"
        Script = "tray.py"
        Arguments = "--config config.json"
        Description = "Run the Govee mode tray icon at logon (hidden)"
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
    Write-Host "user $user"

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
        $arg = "$($t.Script) $($t.Arguments)"
        if ($DryRun) {
            $existing = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
            if ($existing -and $existing.State -eq 'Running') {
                Write-Host "  Would stop running task first"
            }
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
            # Stop any running instance before re-registering
            $existing = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
            if ($existing -and $existing.State -eq 'Running') {
                try {
                    Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
                    Write-Host "Stopped running task: $($t.Name)"
                } catch {
                    # Task may not be running; ignore
                }
            }

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
                    -Force | Out-Null

                Write-Host "Registered task: $($t.Name)"
            } catch {
                Write-Host "ERROR: could not register `"$($t.Name)`": $($_.Exception.Message)" -ForegroundColor Red
                $anyFailed = $true
                continue
            }

            if (-not $NoStart) {
                try {
                    Start-ScheduledTask -TaskName $t.Name
                    $taskInfo = Get-ScheduledTask -TaskName $t.Name
                    Write-Host "Started task: $($t.Name) (State=$($taskInfo.State))"
                } catch {
                    Write-Host "ERROR: registered `"$($t.Name)`" but could not start it: $($_.Exception.Message)" -ForegroundColor Red
                    $anyFailed = $true
                }
            }
        }
    }

    if ($DryRun) {
        Write-Host "[dry-run] Done (no changes made)."
    } else {
        if ($anyFailed) {
            Write-Host "Some tasks failed. Check the errors above." -ForegroundColor Red
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
