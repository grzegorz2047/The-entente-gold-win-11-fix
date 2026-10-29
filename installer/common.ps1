# Shared helpers for install.ps1 and uninstall.ps1.

$ErrorActionPreference = 'Stop'
$AppId = '285480'
$GameExe = 'Antanta.exe'
$BackupDirName = '_win11fix_backup'

function Say([string]$pl, [string]$en, [string]$color = 'Gray') {
    Write-Host "  $pl" -ForegroundColor $color
    Write-Host "  $en" -ForegroundColor DarkGray
}

function Fail([string]$pl, [string]$en) {
    Write-Host ''
    Say "BLAD: $pl" "ERROR: $en" 'Red'
    Write-Host ''
    exit 1
}

# Steam library folders that contain the game (appmanifest_285480.acf), newest Steam layout first.
function Find-GameDir {
    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($key in 'HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam', 'HKLM:\SOFTWARE\Valve\Steam') {
        $p = Get-ItemProperty $key -ErrorAction SilentlyContinue
        foreach ($v in @($p.SteamPath, $p.InstallPath)) { if ($v) { $roots.Add(($v -replace '/', '\')) } }
    }
    $libs = New-Object System.Collections.Generic.List[string]
    foreach ($root in $roots | Select-Object -Unique) {
        $libs.Add($root)
        $vdf = Join-Path $root 'steamapps\libraryfolders.vdf'
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) {
                $libs.Add(($m.Groups[1].Value -replace '\\\\', '\'))
            }
        }
    }
    foreach ($lib in $libs | Select-Object -Unique) {
        $acf = Join-Path $lib "steamapps\appmanifest_$AppId.acf"
        if (-not (Test-Path $acf)) { continue }
        $m = [regex]::Match((Get-Content $acf -Raw), '"installdir"\s+"([^"]+)"')
        $dir = Join-Path $lib ("steamapps\common\" + $(if ($m.Success) { $m.Groups[1].Value } else { 'The Entente Gold' }))
        if (Test-Path (Join-Path $dir $GameExe)) { return $dir }
    }
    return $null
}

function Ask-GameDir {
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = 'Wskaz folder gry The Entente Gold (z plikiem Antanta.exe) / Select The Entente Gold folder (with Antanta.exe)'
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK -and (Test-Path (Join-Path $dlg.SelectedPath $GameExe))) {
        return $dlg.SelectedPath
    }
    return $null
}

function Resolve-GameDir([string]$given) {
    if ($given) {
        if (Test-Path (Join-Path $given $GameExe)) { return (Resolve-Path $given).Path }
        Fail "W folderze '$given' nie ma pliku $GameExe." "There is no $GameExe in '$given'."
    }
    $dir = Find-GameDir
    if (-not $dir) {
        Say 'Nie znalazlem gry automatycznie - wskaz jej folder w okienku.' 'Could not find the game automatically - please select its folder.' 'Yellow'
        $dir = Ask-GameDir
    }
    if (-not $dir) { Fail 'Nie wskazano folderu gry.' 'No game folder selected.' }
    return $dir
}

function Stop-Game {
    $p = Get-Process -Name 'Antanta' -ErrorAction SilentlyContinue
    if ($p) {
        Say 'Gra jest uruchomiona - zamykam ja.' 'The game is running - closing it.' 'Yellow'
        $p | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
}

function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

# Sets the trailing number of line $index in Data\GameInf.txt (cp1251), leaving all other bytes unchanged.
function Set-GameInfValue([string]$gameDir, [int]$index, [int]$value) {
    $path = Join-Path $gameDir 'Data\GameInf.txt'
    if (-not (Test-Path $path)) { return }
    $enc = [Text.Encoding]::GetEncoding(1251)
    $lines = $enc.GetString([IO.File]::ReadAllBytes($path)) -split "`n"
    if ($lines.Count -le $index) { return }
    $lines[$index] = $lines[$index] -replace '(\t+)\d+(\r?)$', "`${1}$value`${2}"
    [IO.File]::WriteAllBytes($path, $enc.GetBytes($lines -join "`n"))
}
