# Build the standalone Windows app: <Out>\HypeToolkit\HypeToolkit.exe (+ a zip next to it).
# Needs the build venv:  powershell -File tools\fetch_wheels.ps1
#                        python -m venv ..\work\hypekit\venv
#                        ..\work\hypekit\venv\Scripts\python -m pip install --no-index --find-links ..\work\hypekit\wheels pywebview pyinstaller
#   powershell -File tools\build_windows.ps1 [-Out <dir>] [-Vgm <vgmstream folder>]
# Bundles vgmstream-cli (ISC licence, COPYING included) for Ubi MPEG. No game files are bundled.
param(
    [string]$Out = (Join-Path $PSScriptRoot '..\..\work\hypekit\dist'),
    [string]$Vgm = (Join-Path $PSScriptRoot '..\..\sources\tools\vgmstream')
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$work = (Resolve-Path (Join-Path $repo '..\work')).Path
$py = Join-Path $work 'hypekit\venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "build venv missing: $py (see the header of this script)" }
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path

$pyi = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--name', 'HypeToolkit',
          '--distpath', $Out, '--workpath', (Join-Path $work 'hypekit\build'), '--specpath', (Join-Path $work 'hypekit\build'),
          '--paths', $repo, '--collect-submodules', 'hypekit',
          '--add-data', "$repo\hypekit\web;hypekit\web")
if (Test-Path (Join-Path $Vgm 'vgmstream-cli.exe')) {
    foreach ($f in Get-ChildItem $Vgm -File | Where-Object { $_.Extension -in '.exe', '.dll' }) {
        $pyi += @('--add-binary', "$($f.FullName);vendor\vgmstream")
    }
    if (Test-Path "$Vgm\COPYING") { $pyi += @('--add-data', "$Vgm\COPYING;vendor\vgmstream") }
} else { Write-Host "warning: no vgmstream in $Vgm - voices and music (Ubi MPEG) will not play" }
$pyi += (Join-Path $repo 'tools\hypekit_app.py')

$log = Join-Path $work 'hypekit\build.log'
$ErrorActionPreference = 'Continue'              # PyInstaller logs to stderr; PowerShell 5.1 would treat that as an error
& $py @pyi 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Encoding utf8
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code) { Get-Content $log -Tail 25; throw "PyInstaller failed ($code), log: $log" }
$app = Join-Path $Out 'HypeToolkit'
$zip = Join-Path $Out 'HypeToolkit-win64.zip'
if (Test-Path $zip) { Remove-Item $zip -Force -Confirm:$false }
Add-Type -AssemblyName System.IO.Compression.FileSystem
for ($i = 1; ; $i++) {                            # fresh files can be locked for a moment by the virus scanner
    try { [IO.Compression.ZipFile]::CreateFromDirectory($app, $zip, 'Optimal', $true); break }
    catch { if ($i -ge 5) { throw }; if (Test-Path $zip) { Remove-Item $zip -Force -Confirm:$false }; Start-Sleep 3 }
}
$mb = [math]::Round((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "built $app\HypeToolkit.exe ($mb MB), zip: $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
Write-Host "log: $log"
