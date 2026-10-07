param(
    [switch]$Watch,
    [switch]$NoBrowser,
    [int]$TimeoutSeconds = 300,
    [int]$LauncherPid = 0
)

$ErrorActionPreference = 'Stop'
$serverPort = 5000
if ($env:GIFT_PORT) { $serverPort = [int]$env:GIFT_PORT }
if ($serverPort -lt 1 -or $serverPort -gt 65535) { throw 'Invalid GIFT_PORT.' }
$serverHost = $env:GIFT_HOST
if (-not $serverHost -or $serverHost -eq '0.0.0.0') { $serverHost = '127.0.0.1' }
if ($serverHost -eq '::') { $serverHost = '[::1]' }
$serverUrl = "http://${serverHost}:${serverPort}/"

function Get-ServerState {
    try {
        $page = Invoke-WebRequest -Uri $serverUrl -UseBasicParsing -TimeoutSec 2
        if ($page.StatusCode -eq 200 -and $page.Content -match '<form\s+action="/login"') {
            return 'Ready'
        }
        return 'Other'
    } catch {
        if ($_.Exception.Response) { return 'Other' }
        return 'Waiting'
    }
}

function Open-Program {
    if (-not $NoBrowser) { Start-Process $serverUrl }
    Write-Output "Ready: $serverUrl"
}

if ($Watch) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($LauncherPid -and -not (Get-Process -Id $LauncherPid -ErrorAction SilentlyContinue)) { exit 1 }
        $state = Get-ServerState
        if ($state -eq 'Ready') { Open-Program; exit 0 }
        if ($state -eq 'Other') { exit 20 }
        Start-Sleep -Milliseconds 500
    }
    exit 1
}

$state = Get-ServerState
if ($state -eq 'Ready') { Open-Program; exit 10 }
if ($state -eq 'Other') {
    Write-Output "Another application is using $serverUrl. Stop it or choose another GIFT_PORT."
    exit 20
}

$parentPid = (Get-CimInstance Win32_Process -Filter "ProcessId = $PID").ParentProcessId
$watchArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Watch -LauncherPid $parentPid -TimeoutSeconds $TimeoutSeconds"
if ($NoBrowser) { $watchArguments += ' -NoBrowser' }
Start-Process -FilePath 'powershell.exe' -ArgumentList $watchArguments -WindowStyle Hidden | Out-Null
Write-Output "The browser will open when the server is ready: $serverUrl"
exit 0
