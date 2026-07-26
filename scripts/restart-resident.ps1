[CmdletBinding()]
param(
    [string]$TaskName = "\Codex Pico Panel",
    [uri]$StatusUrl = "http://127.0.0.1:48973/api/status",
    [ValidateRange(1, 120)]
    [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"

function Test-ResidentStatus {
    try {
        $response = Invoke-WebRequest `
            -Uri $StatusUrl `
            -UseBasicParsing `
            -TimeoutSec 1

        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-ResidentStatus {
    param(
        [bool]$Expected
    )

    $timer = [System.Diagnostics.Stopwatch]::StartNew()

    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if ((Test-ResidentStatus) -eq $Expected) {
            return $true
        }

        Start-Sleep -Milliseconds 250
    }

    return $false
}

if (Test-ResidentStatus) {
    $shutdownUrl = [uri]::new(
        $StatusUrl,
        "/api/shutdown"
    )

    Invoke-WebRequest `
        -Uri $shutdownUrl `
        -Method Post `
        -UseBasicParsing `
        -TimeoutSec 3 |
        Out-Null

    if (-not (Wait-ResidentStatus -Expected $false)) {
        throw "Resident did not stop within $TimeoutSeconds seconds."
    }
}

& schtasks.exe /Run /TN $TaskName | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "Could not start scheduled task '$TaskName'."
}

if (-not (Wait-ResidentStatus -Expected $true)) {
    throw "Resident did not start within $TimeoutSeconds seconds."
}

$status = Invoke-RestMethod `
    -Uri $StatusUrl `
    -TimeoutSec 2

Write-Host (
    "Codex Pico Panel restarted: Pico={0}, Port={1}" -f
    $status.pico_connected,
    $status.pico_port
)
