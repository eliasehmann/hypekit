# Download the build/app wheels from PyPI with PowerShell (schannel: works behind the TLS interception where pip
# fails), for offline install:  pip install --no-index --find-links <dir> pywebview pyinstaller
#   powershell -File tools\fetch_wheels.ps1 [-Out <dir>] [-Py 310]
param(
    [string]$Out = (Join-Path $PSScriptRoot '..\..\work\hypekit\wheels'),
    [string]$Py = '310'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force $Out | Out-Null

# app window: pywebview (+ pythonnet for WebView2 on Windows); build: pyinstaller
$pkgs = 'pywebview', 'proxy_tools', 'bottle', 'typing_extensions', 'pythonnet', 'clr_loader', 'cffi', 'pycparser',
        'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'pefile', 'pywin32-ctypes', 'packaging', 'setuptools'

# best wheel: CPython <Py> win_amd64, then abi3 win_amd64, then pure python
function Pick($files) {
    $wh = $files | Where-Object { $_.packagetype -eq 'bdist_wheel' }
    foreach ($pat in "cp$Py-cp$Py-win_amd64", "abi3-win_amd64", "-none-win_amd64", "py3-none-any", "py2.py3-none-any") {
        $m = $wh | Where-Object { $_.filename -like "*$pat.whl" } | Select-Object -First 1
        if ($m) { return $m }
    }
    return $null
}

# versions that still support Python 3.10 (newer ones need 3.11+)
$pins = @{ '310' = @{ 'pythonnet' = '3.0.5'; 'clr_loader' = '0.2.9'; 'pycparser' = '2.23' } }

$got = 0
foreach ($p in $pkgs) {
    $v = $pins[$Py][$p]
    $j = Invoke-RestMethod ("https://pypi.org/pypi/$p/" + $(if ($v) { "$v/" } else { '' }) + 'json')
    $f = Pick $j.urls
    if (-not $f) { $f = $j.urls | Where-Object { $_.packagetype -eq 'sdist' } | Select-Object -First 1 }   # pure-python sdist (proxy_tools)
    if (-not $f) { Write-Host "nothing for $p $($j.info.version)"; continue }
    if ($j.info.requires_python) { Write-Host ("    requires python {0}" -f $j.info.requires_python) }
    $dest = Join-Path $Out $f.filename
    if (-not (Test-Path $dest)) { Invoke-WebRequest $f.url -OutFile $dest -UseBasicParsing }
    $got++
    Write-Host ("{0,-28} {1}" -f $p, $f.filename)
}
Write-Host "$got wheels in $((Resolve-Path $Out).Path)"
