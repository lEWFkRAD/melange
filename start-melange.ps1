param([ValidateRange(1,65535)][int]$Port = 8798)
$ErrorActionPreference = 'Stop'
Write-Host "Melange: http://localhost:$Port"
Write-Host 'Keep this window open. Press Ctrl+C to stop.'
wsl.exe --cd $PSScriptRoot env "MELANGE_PORT=$Port" python3 service/melange_service.py
exit $LASTEXITCODE
