<#
.SYNOPSIS
    Runs the GeoFA plugin's end-to-end checks in real QGIS windows (QGIS 3.44 LTR and QGIS 4).

.DESCRIPTION
    Copies geofa_plugin/ into a fresh QGIS profile under dev/qgis-profile (not committed), starts
    QGIS with tests/e2e/gui_smoke.py and then with tests/e2e/exit_check.py, and reports each check.
    GeoFA's production and test environments are only read, anonymously: no login is used or stored.
    Checks marked (testmiljo) are warnings only: GeoFA's test environment isn't always available.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tests\e2e\run_e2e.ps1
    powershell -ExecutionPolicy Bypass -File tests\e2e\run_e2e.ps1 -Versions ltr
    powershell -ExecutionPolicy Bypass -File tests\e2e\run_e2e.ps1 -Zip dev\dist\GeoFA-1.0.0.zip
#>
param(
    [ValidateSet("ltr", "latest")] [string[]] $Versions = @("ltr", "latest"),
    [string] $Zip = "",  # install the plugin from this release ZIP instead of from geofa_plugin/
    [string] $OSGeo4W = $(if (Test-Path "$env:LOCALAPPDATA\Programs\OSGeo4W") { "$env:LOCALAPPDATA\Programs\OSGeo4W" } else { "C:\OSGeo4W" }),
    [int] $TimeoutSeconds = 180
)

$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$profiles = Join-Path $repo "dev\qgis-profile"
$profileDir = Join-Path $profiles "profiles\e2e"
$out = Join-Path $repo "dev\reports\e2e"
$launchers = @{ ltr = @("qgis-ltr.bat", "qgis-ltr-bin"); latest = @("qgis.bat", "qgis-bin") }

# A fresh profile with only this plugin, switched on (the same files as the release ZIP)
if (Test-Path $profileDir) { Remove-Item -Recurse -Force $profileDir }
New-Item -ItemType Directory -Force (Join-Path $profileDir "QGIS"), $out | Out-Null
if ($Zip) {
    Expand-Archive -Path (Resolve-Path $Zip) -DestinationPath (Join-Path $profileDir "python\plugins") -Force
    Write-Host "Plugin installed from $Zip"
} else {
    robocopy (Join-Path $repo "geofa_plugin") (Join-Path $profileDir "python\plugins\geofa") /E /XD test Vejledning __pycache__ /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
}
foreach ($ini in "QGIS3.ini", "QGIS4.ini") {
    [IO.File]::WriteAllText((Join-Path $profileDir "QGIS\$ini"), "[PythonPlugins]`r`ngeofa=true`r`n")
}

function Invoke-Qgis([string] $version, [string] $script) {
    $bat, $exe = $launchers[$version]
    $before = @(Get-Process $exe -ErrorAction SilentlyContinue | ForEach-Object Id)
    $env:GEOFA_E2E_OUT = $out
    $started = Get-Date
    Start-Process -FilePath (Join-Path $OSGeo4W "bin\$bat") -WindowStyle Minimized -ArgumentList @(
        "--profiles-path", "`"$profiles`"", "--profile", "e2e", "--nologo", "--noversioncheck", "--code", "`"$script`"")
    # The .bat starts QGIS and returns at once: find the new QGIS process
    $process = $null
    for ($i = 0; $i -lt 60 -and -not $process; $i++) {
        Start-Sleep -Seconds 1
        $process = Get-Process $exe -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Select-Object -First 1
    }
    if (-not $process) { return @{ started = $false } }
    $exited = $process.WaitForExit($TimeoutSeconds * 1000)
    if (-not $exited) { Stop-Process -Id $process.Id -Force }
    $crash = Get-ChildItem $env:TEMP -Filter "qgis-python-crash-info-$($process.Id)" -ErrorAction SilentlyContinue |
        Where-Object Length -gt 0
    return @{ started = $true; exited = $exited; seconds = [int]((Get-Date) - $started).TotalSeconds; crash = [bool]$crash }
}

$failed = 0
function Report([bool] $passed, [string] $name, [string] $seen = "", [bool] $warningOnly = $false) {
    if ($passed) { Write-Host "  ok    $name"; return }
    if ($warningOnly) { Write-Host "  WARN  $name  ($seen)" -ForegroundColor Yellow; return }
    Write-Host "  FAIL  $name  ($seen)" -ForegroundColor Red
    $script:failed++
}

foreach ($version in $Versions) {
    Remove-Item (Join-Path $out "*") -ErrorAction SilentlyContinue

    Write-Host "== QGIS $version`: the plugin in a QGIS window"
    $run = Invoke-Qgis $version (Join-Path $PSScriptRoot "gui_smoke.py")
    $json = Get-ChildItem $out -Filter "gui_smoke_*.json" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $json) {
        Report $false "result written" "started=$($run.started) exited=$($run.exited) crash=$($run.crash); see $out"
        continue
    }
    $result = Get-Content $json.FullName -Raw -Encoding utf8 | ConvertFrom-Json
    Write-Host "  QGIS $($result.qgis)"
    foreach ($check in $result.checks.PSObject.Properties) {
        Report $check.Value.passed $check.Name $check.Value.seen ($check.Name -like "*(testmilj*")
    }
    Report (-not $result.error) "no Python errors" $result.error
    Report ($run.exited -and -not $run.crash) "QGIS closed by itself, no crash" "exited=$($run.exited) crash=$($run.crash)"

    Write-Host "== QGIS $version`: closing QGIS with a GeoFA layer loaded"
    $run = Invoke-Qgis $version (Join-Path $PSScriptRoot "exit_check.py")
    Report ($run.exited -and -not $run.crash -and $run.seconds -lt 90) "QGIS closed in $($run.seconds) s" `
        "exited=$($run.exited) crash=$($run.crash)"
}

if ($failed) { Write-Host "$failed check(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "All checks passed" -ForegroundColor Green
exit 0
