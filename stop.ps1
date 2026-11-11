$ErrorActionPreference = 'Stop'
# Match only this directory's two entrypoints; never kill an arbitrary port owner.
$root = $PSScriptRoot
[IO.File]::WriteAllText((Join-Path $root '.stopped'), 'Stopped by stop.cmd')
$supervisor = [regex]::Escape((Join-Path $root 'supervisor.py'))
$notifier = [regex]::Escape((Join-Path $root 'notifier.py'))
$targets = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and
    ($_.CommandLine -match ($supervisor + '("|\s|$)') -or $_.CommandLine -match ($notifier + '("|\s|$)'))
})
$ids = @($targets.ProcessId)
foreach ($process in $targets) {
    if ($ids -notcontains $process.ParentProcessId) {
        & taskkill.exe /PID $process.ProcessId /T /F | Out-Null
    }
}
Start-Sleep -Milliseconds 500
$remaining = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and
    ($_.CommandLine -match ($supervisor + '("|\s|$)') -or $_.CommandLine -match ($notifier + '("|\s|$)'))
})
if ($remaining.Count) { throw 'Notification processes are still running' }
Write-Output 'Stopped: notifier and watchdog. No unrelated bot processes were targeted.'
