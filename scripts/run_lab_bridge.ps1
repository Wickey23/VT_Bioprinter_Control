param(
  [string]$ArduinoPort = "COM6",
  [string]$PrinterPort = "COM5"
)

$ErrorActionPreference = "Stop"

Write-Host "VT Bioprinter lab bridge setup" -ForegroundColor Cyan
Write-Host "Arduino: $ArduinoPort"
Write-Host "Printer: $PrinterPort"
Write-Host ""

# Verify the expected serial ports are present.
$ports = Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Name, Description

$arduinoFound = $ports | Where-Object { $_.DeviceID -eq $ArduinoPort }
$printerFound = $ports | Where-Object { $_.DeviceID -eq $PrinterPort }

if (-not $arduinoFound) {
  Write-Error "Arduino port $ArduinoPort was not found. Reconnect the DFRduino and check Device Manager."
}

if (-not $printerFound) {
  Write-Error "Printer port $PrinterPort was not found. Reconnect the Creality controller USB cable."
}

Write-Host "Detected serial devices:" -ForegroundColor Green
$ports | Format-Table -AutoSize

# Find Python.
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
  $python = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $python = "python"
} else {
  Write-Error "Python was not found. Install Python 3, then rerun this script."
}

Write-Host ""
Write-Host "Ensuring pyserial is installed..." -ForegroundColor Cyan
& $python -m pip install --disable-pip-version-check pyserial

$repoRoot = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $repoRoot "host_bridge\arduino_to_marlin_bridge.py"

if (-not (Test-Path $bridge)) {
  Write-Error "Bridge script not found at $bridge"
}

Write-Host ""
Write-Host "IMPORTANT:" -ForegroundColor Yellow
Write-Host "1. The DFRduino must already have arduino\command_sender\command_sender.ino uploaded."
Write-Host "2. Close Arduino Serial Monitor before continuing."
Write-Host "3. This bridge is in SAFE MODE and forwards only M105, M115, M119, and M503."
Write-Host ""
Write-Host "Starting bridge..." -ForegroundColor Green

& $python $bridge --arduino $ArduinoPort --printer $PrinterPort
