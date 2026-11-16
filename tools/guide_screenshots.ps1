<#
.SYNOPSIS
    Takes the screenshots for the Danish guide in a real QGIS window (QGIS 3.44 LTR by default).

.DESCRIPTION
    Copies geofa_plugin/ into a fresh QGIS profile under dev/qgis-profile (not committed), starts QGIS
    with tools/guide_screenshots.py, and waits for it to close. The images are written to
    geofa_plugin/Vejledning, next to the guide that shows them. GeoFA is only read, anonymously.
    The QGIS window shows on screen while the script runs (about 40 seconds): the map only draws
    in a visible window.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\guide_screenshots.ps1
    powershell -ExecutionPolicy Bypass -File tools\guide_screenshots.ps1 -Version latest
#>
param(
    [ValidateSet("ltr", "latest")] [string] $Version = "ltr",
    [string] $OSGeo4W = $(if (Test-Path "$env:LOCALAPPDATA\Programs\OSGeo4W") { "$env:LOCALAPPDATA\Programs\OSGeo4W" } else { "C:\OSGeo4W" }),
    [int] $TimeoutSeconds = 180
)

$repo = (Resolve-Path "$PSScriptRoot\..").Path
$profiles = Join-Path $repo "dev\qgis-profile"
$profileDir = Join-Path $profiles "profiles\guide"
$out = Join-Path $repo "geofa_plugin\Vejledning"
$launchers = @{ ltr = @("qgis-ltr.bat", "qgis-ltr-bin"); latest = @("qgis.bat", "qgis-bin") }

# A fresh profile with only this plugin, switched on (the same files as the release ZIP)
if (Test-Path $profileDir) { Remove-Item -Recurse -Force $profileDir }
New-Item -ItemType Directory -Force (Join-Path $profileDir "QGIS"), $out | Out-Null
robocopy (Join-Path $repo "geofa_plugin") (Join-Path $profileDir "python\plugins\geofa") /E /XD test Vejledning __pycache__ /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
foreach ($ini in "QGIS3.ini", "QGIS4.ini") {
    [IO.File]::WriteAllText((Join-Path $profileDir "QGIS\$ini"), "[PythonPlugins]`r`ngeofa=true`r`n")
}

$bat, $exe = $launchers[$Version]
$before = @(Get-Process $exe -ErrorAction SilentlyContinue | ForEach-Object Id)
$env:GEOFA_GUIDE_OUT = $out
Start-Process -FilePath (Join-Path $OSGeo4W "bin\$bat") -ArgumentList @(
    "--profiles-path", "`"$profiles`"", "--profile", "guide", "--nologo", "--noversioncheck",
    "--code", "`"$(Join-Path $PSScriptRoot 'guide_screenshots.py')`"")
$process = $null
for ($i = 0; $i -lt 60 -and -not $process; $i++) {
    Start-Sleep -Seconds 1
    $process = Get-Process $exe -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Select-Object -First 1
}
if (-not $process) { Write-Host "QGIS didn't start" -ForegroundColor Red; exit 1 }
if (-not $process.WaitForExit($TimeoutSeconds * 1000)) { Stop-Process -Id $process.Id -Force; Write-Host "QGIS was stopped after $TimeoutSeconds s" -ForegroundColor Red }
$log = Join-Path $out "guide_screenshots.log"
if (Test-Path $log) { Get-Content $log; Remove-Item $log }
Get-ChildItem $out -Filter *.png | ForEach-Object { "{0,-18} {1,6} KB" -f $_.Name, [int]($_.Length / 1KB) }
