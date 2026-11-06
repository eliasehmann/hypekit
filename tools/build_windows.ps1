# Build the standalone Windows app as ONE file: <Out>\HypeToolkit.exe (unpacks itself to %TEMP% at each start).
# Needs the build venv:  powershell -File tools\fetch_wheels.ps1
#                        python -m venv ..\work\hypekit\venv
#                        ..\work\hypekit\venv\Scripts\python -m pip install --no-index --find-links ..\work\hypekit\wheels pywebview pyinstaller
#   powershell -File tools\build_windows.ps1 [-Out <dir>] [-Vgm <vgmstream folder>] [-Folder]
#   -Folder: the old one-folder build (<Out>\HypeToolkit\HypeToolkit.exe + _internal), starts faster, for development.
# Bundles vgmstream-cli + libmpg123 (the only DLL the game's MPEG audio needs) with their licence, NOTICE.txt and the
# app icon (assets\icon.ico, tools\make_icon.py). No game files are bundled.
param(
    [string]$Out = (Join-Path $PSScriptRoot '..\..\work\hypekit\dist'),
    [string]$Vgm = (Join-Path $PSScriptRoot '..\..\sources\tools\vgmstream'),
    [switch]$Folder
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$work = (Resolve-Path (Join-Path $repo '..\work')).Path
$py = Join-Path $work 'hypekit\venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "build venv missing: $py (see the header of this script)" }
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path

$pyi = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--name', 'HypeToolkit', $(if ($Folder) { '--onedir' } else { '--onefile' }),
          '--icon', "$repo\assets\icon.ico",
          '--distpath', $Out, '--workpath', (Join-Path $work 'hypekit\build'), '--specpath', (Join-Path $work 'hypekit\build'),
          '--paths', $repo, '--collect-submodules', 'hypekit',
          '--add-data', "$repo\hypekit\web;hypekit\web", '--add-data', "$repo\NOTICE.txt;.")
if (Test-Path (Join-Path $Vgm 'vgmstream-cli.exe')) {
    foreach ($f in 'vgmstream-cli.exe', 'libmpg123-0.dll') { $pyi += @('--add-binary', "$Vgm\$f;vendor\vgmstream") }
    if (Test-Path "$Vgm\COPYING") { $pyi += @('--add-data', "$Vgm\COPYING;vendor\vgmstream") }
} else { Write-Host "warning: no vgmstream in $Vgm - voices and music (Ubi MPEG) will not play" }
$pyi += (Join-Path $repo 'tools\hypekit_app.py')

$log = Join-Path $work 'hypekit\build.log'
$ErrorActionPreference = 'Continue'              # PyInstaller logs to stderr; PowerShell 5.1 would treat that as an error
& $py @pyi 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Encoding utf8
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code) { Get-Content $log -Tail 25; throw "PyInstaller failed ($code), log: $log" }
$exe = if ($Folder) { Join-Path $Out 'HypeToolkit\HypeToolkit.exe' } else { Join-Path $Out 'HypeToolkit.exe' }
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "built $exe ($mb MB)"
Write-Host "log: $log"
