# Start the local HTTP server without a terminal window.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the Python virtual environment first.' }
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot '.env'))) { throw 'Configure the local .env file first.' }
$logDirectory = Join-Path $repoRoot '.local'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
# A named mutex serializes startup attempts from shortcuts and manual launches.
$startupMutex = New-Object System.Threading.Mutex($false, 'Local\SettleUpMCP-Sandbox-Startup')
$locked = $false
try {
    $locked = $startupMutex.WaitOne(10000)
    if (-not $locked) { throw 'Another server startup is in progress.' }
    $health = $null
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
    } catch {
        # Windows PowerShell and PowerShell 7 use different network exceptions.
    }
    if ($health) {
        if ($health.server -eq 'settleup_mcp' -and $health.environment -eq 'sandbox') {
            Write-Output 'Settle Up sandbox is already running.'
            return
        }
        throw 'Port 8000 is occupied by another application.'
    }
    $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'settleup_mcp.local_server') -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'server-out.log') -RedirectStandardError (Join-Path $logDirectory 'server-error.log') -PassThru
    Set-Content -LiteralPath (Join-Path $logDirectory 'server.pid') -Value $serverProcess.Id
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Milliseconds 1000
        $serverProcess.Refresh()
        if ($serverProcess.HasExited) { throw 'Server exited. Inspect the private .local logs.' }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
            if ($health.server -eq 'settleup_mcp' -and $health.environment -eq 'sandbox') {
                Write-Output "Settle Up sandbox is ready (PID $($serverProcess.Id))."
                return
            }
        } catch {
            # Wait for the application to finish starting.
        }
    }
    throw 'Server has not become ready. Inspect the private .local logs.'
} finally {
    if ($locked) { $startupMutex.ReleaseMutex() }
    $startupMutex.Dispose()
}
