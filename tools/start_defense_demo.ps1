[CmdletBinding()]
param(
    [ValidateSet("listener", "wakeword")]
    [string]$VoiceMode = "listener",
    [string]$InputDevice = "1",
    [int]$ReadyWaitSeconds = 180,
    [switch]$SkipVoice,
    [switch]$NoBrowser,
    [switch]$ListAudioDevices,
    [switch]$LocalPreview,
    [string]$Esp32Port = "COM8",
    [switch]$DisableEsp32AutoRepair,
    [switch]$ConfigureHotspot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$BaseUrl = "https://yh001399-smart-desktop-ai-terminal.hf.space"
$LocalPreviewUrl = "http://127.0.0.1:8083/console"
$DeviceId = "desktop-agent-001"
$RelayPort = 8091
$ReadinessScript = Join-Path $PSScriptRoot "realtime_readiness_check.py"
$RelayLogDirectory = Join-Path $ProjectRoot ".tmp\defense-demo"
$RelayStdout = Join-Path $RelayLogDirectory "esp32-relay.stdout.log"

function Quote-ProcessArgument([string]$Value) {
    if ($Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Join-ProcessArguments([string[]]$Arguments) {
    return ($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join " "
}

function Test-RelayListening {
    return @(
        Get-NetTCPConnection -State Listen -LocalPort $RelayPort -ErrorAction SilentlyContinue
    ).Count -gt 0
}

function Get-PreferredLanAddress {
    $physicalAdapters = @(
        Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
            Where-Object { $_.Status -eq "Up" }
    )
    foreach ($adapter in $physicalAdapters) {
        $address = @(
            Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.IPAddress -notlike "127.*" -and
                    $_.IPAddress -notlike "169.254.*"
                }
        ) | Select-Object -First 1 -ExpandProperty IPAddress
        if ($address) {
            return $address
        }
    }

    return @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.IPAddress -notlike "198.18.*" -and
                $_.InterfaceAlias -notmatch "(?i)loopback|meta|tunnel|vpn"
            }
    ) | Select-Object -First 1 -ExpandProperty IPAddress
}

function Test-RecentRelayTraffic {
    if (-not (Test-Path $RelayStdout)) {
        return $false
    }
    return ((Get-Date) - (Get-Item $RelayStdout).LastWriteTime).TotalSeconds -le 30
}

function Test-SerialPortPresent([string]$PortName) {
    return [System.IO.Ports.SerialPort]::GetPortNames() -contains $PortName
}

function Repair-Esp32RelayTarget {
    if ($DisableEsp32AutoRepair) {
        Write-Host "[relay] ESP32 auto-repair disabled by option."
        return
    }
    if (Test-RecentRelayTraffic) {
        Write-Host "[relay] Recent ESP32 traffic exists; keeping its current configuration."
        return
    }

    $lanAddress = Get-PreferredLanAddress
    if (-not $lanAddress) {
        Write-Host "[relay] No active LAN IPv4 address found. Connect the laptop to the demo hotspot first."
        return
    }
    if (-not (Test-SerialPortPresent $Esp32Port)) {
        Write-Host "[relay] $Esp32Port is not present; cannot update ESP32 automatically."
        return
    }

    $relayUrl = "http://${lanAddress}:$RelayPort"
    Write-Host "[relay] No recent ESP32 traffic. Updating $Esp32Port server target to $relayUrl..."
    $repairArguments = @(
        "-B", (Join-Path $PSScriptRoot "configure_esp32.py"),
        "--port", $Esp32Port,
        "--server", $relayUrl,
        "--server-only",
        "--open-delay", "8"
    )
    & $Python @repairArguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[relay] Automatic ESP32 server update failed; readiness checks will continue."
        return
    }
    Write-Host "[relay] ESP32 server target updated. Waiting for Wi-Fi and UART recovery."
}

function Configure-Esp32Hotspot {
    $lanAddress = Get-PreferredLanAddress
    if (-not $lanAddress) {
        throw "No physical LAN/Wi-Fi IPv4 address found. Connect the laptop to your hotspot first."
    }
    if (-not (Test-SerialPortPresent $Esp32Port)) {
        throw "$Esp32Port is not present. Connect the ESP32 USB cable before configuring the hotspot."
    }

    $relayUrl = "http://${lanAddress}:$RelayPort"
    Write-Host "[hotspot] Enter the hotspot used by both the laptop and ESP32."
    Write-Host "[hotspot] The password is sent to ESP32 over USB and is not saved by this script."
    $configureArguments = @(
        "-B", (Join-Path $PSScriptRoot "configure_esp32.py"),
        "--port", $Esp32Port,
        "--server", $relayUrl,
        "--prompt-wifi",
        "--open-delay", "8"
    )
    & $Python @configureArguments
    if ($LASTEXITCODE -ne 0) {
        throw "ESP32 hotspot configuration failed."
    }
    Write-Host "[hotspot] ESP32 hotspot and relay target saved."
}

function Start-RelayIfMissing {
    if (Test-RelayListening) {
        Write-Host "[relay] Existing listener found on port $RelayPort; keeping it."
        return
    }

    New-Item -ItemType Directory -Force -Path $RelayLogDirectory | Out-Null
    $stderr = Join-Path $RelayLogDirectory "esp32-relay.stderr.log"
    $relayScript = Join-Path $PSScriptRoot "esp32_hf_relay.py"
    $relayStartOptions = @{
        FilePath = $Python
        ArgumentList = Join-ProcessArguments @("-u", $relayScript, "--host", "0.0.0.0", "--port", "$RelayPort")
        WorkingDirectory = $ProjectRoot
        RedirectStandardOutput = $RelayStdout
        RedirectStandardError = $stderr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $process = Start-Process @relayStartOptions

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-RelayListening) {
            Write-Host "[relay] Started PID $($process.Id). Logs: $RelayLogDirectory"
            return
        }
    }

    throw "Relay did not start listening on port $RelayPort. Check $stderr."
}

function Wait-ForReadiness {
    if ($ReadyWaitSeconds -lt 0) {
        throw "ReadyWaitSeconds must not be negative."
    }

    $deadline = (Get-Date).AddSeconds($ReadyWaitSeconds)
    $lanAddress = Get-PreferredLanAddress
    if ($lanAddress) {
        Write-Host "[relay] Current ESP32 server URL: http://${lanAddress}:$RelayPort"
    }
    $repairAttempted = $false
    do {
        Write-Host "[check] Read-only check: cloud, ESP32, UART, and sensor freshness..."
        & $Python -B $ReadinessScript --base-url $BaseUrl --device-id $DeviceId --compact
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[check] PASS: web, mini-program, and voice demo may begin."
            return
        }

        if (-not $repairAttempted) {
            Repair-Esp32RelayTarget
            $repairAttempted = $true
        }
        if ((Get-Date) -ge $deadline) {
            throw "Hardware did not become ready within $ReadyWaitSeconds seconds. Confirm ESP32 power/Wi-Fi and its CFG:SERVER address shown above."
        }
        Write-Host "[check] Not ready; retrying in 5 seconds (ESP32 boot may take 1-3 minutes)."
        Start-Sleep -Seconds 5
    } while ($true)
}

function Start-LocalPreviewBackend {
    Write-Host "[web] Starting local preview backend for updated UI..."
    & $Python -B (Join-Path $PSScriptRoot "start_backend.py") --bind-host 0.0.0.0 --health-host 127.0.0.1 --port 8083 --timeout 20
    if ($LASTEXITCODE -ne 0) {
        throw "Local preview backend did not start. Use the public console or inspect the backend logs."
    }
}

function Get-VoiceProcess {
    return @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -match '(?i)(laptop_realtime_listener|laptop_wakeword_sidecar)\.py'
        }
    )
}

function Quote-PowerShellValue([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Start-VoiceFrontend {
    $running = @(Get-VoiceProcess)
    if ($running.Count -gt 0) {
        $ids = ($running | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Host "[voice] Existing voice frontend PID(s): $ids. Not starting another one."
        return
    }
    if ($SkipVoice) {
        Write-Host "[voice] Skipped by -SkipVoice."
        return
    }

    Write-Host "[voice] Laptop microphone device: $InputDevice."
    Write-Host "[privacy] The voice frontend records and uploads audio to cloud ASR only after confirmation."
    $answer = Read-Host "Press Enter to start voice; type N for web/mini-program only"
    if ($answer -match '(?i)^n') {
        Write-Host "[voice] Voice frontend skipped."
        return
    }

    if ($VoiceMode -eq "listener") {
        $voiceScript = Join-Path $PSScriptRoot "laptop_realtime_listener.py"
        $voiceArguments = @(
            "-u", $voiceScript,
            "--base-url", $BaseUrl,
            "--device-id", $DeviceId,
            "--input-device", $InputDevice,
            "--input-mode", "ptt",
            "--no-auto-start-backend"
        )
    } else {
        $voiceScript = Join-Path $PSScriptRoot "laptop_wakeword_sidecar.py"
        $voiceArguments = @(
            "-u", $voiceScript,
            "--base-url", $BaseUrl,
            "--device-id", $DeviceId,
            "--input-device", $InputDevice,
            "--confirm-start"
        )
    }

    $command = "& " + (Quote-PowerShellValue $Python)
    foreach ($argument in $voiceArguments) {
        $command += " " + (Quote-PowerShellValue $argument)
    }
    $voiceStartOptions = @{
        FilePath = "powershell.exe"
        ArgumentList = Join-ProcessArguments @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $command)
        WorkingDirectory = $ProjectRoot
    }
    Start-Process @voiceStartOptions
    Write-Host "[voice] Started $VoiceMode frontend in a separate window. Stop it there with Ctrl+C."
}

if ($ListAudioDevices) {
    & $Python -B (Join-Path $PSScriptRoot "laptop_realtime_listener.py") --list-devices
    exit $LASTEXITCODE
}

Write-Host "[demo] Network, VPN, DNS, routes, and firewall are not changed."
Start-RelayIfMissing
if ($ConfigureHotspot) {
    Configure-Esp32Hotspot
}
Wait-ForReadiness

if (-not $NoBrowser) {
    if ($LocalPreview) {
        Start-LocalPreviewBackend
        Start-Process $LocalPreviewUrl
        Write-Host "[web] Requested opening local updated console: $LocalPreviewUrl"
        Write-Host "[web] Note: local preview may not show live ESP32 data if the device is configured for the public backend."
    } else {
        Start-Process "$BaseUrl/console"
        Write-Host "[web] Requested opening the public console: $BaseUrl/console"
        Write-Host "[web] Note: local frontend edits only appear on this public URL after deploying to Hugging Face."
        Write-Host "[web] For local UI preview now, run: .\tools\start_defense_demo.cmd -LocalPreview"
    }
}

Start-VoiceFrontend
Write-Host "[demo] Startup complete: web and mini-program share Hugging Face state; voice uses the laptop mic frontend."
