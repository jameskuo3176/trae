param(
    [string]$PythonExe = (Get-Command python.exe -ErrorAction Stop).Source
)

$ErrorActionPreference = "Stop"
$handler = (Resolve-Path (Join-Path $PSScriptRoot "gvim_protocol_handler.py")).Path
$baseKey = "HKCU:\Software\Classes\gvim"

New-Item -Path $baseKey -Force | Out-Null
Set-ItemProperty -Path $baseKey -Name "(Default)" -Value "URL:QoR gvim source file"
Set-ItemProperty -Path $baseKey -Name "URL Protocol" -Value ""
New-Item -Path "$baseKey\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$baseKey\DefaultIcon" -Name "(Default)" -Value "gvim.exe,0"
New-Item -Path "$baseKey\shell\open\command" -Force | Out-Null

$command = "`"$PythonExe`" `"$handler`" `"%1`""
Set-ItemProperty -Path "$baseKey\shell\open\command" -Name "(Default)" -Value $command

Write-Host "Registered gvim:// for the current Windows user."
Write-Host "Test with: gvim://open?path=C%3A%5Ctemp%5Ctest.txt&line=1"
