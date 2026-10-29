# Installs the Windows 10/11 fix for The Entente Gold (Steam).
# Started by Install.cmd; can also be run as: install.ps1 [-GameDir "<folder with Antanta.exe>"]
param([string]$GameDir)

. (Join-Path $PSScriptRoot 'common.ps1')

$DgVoodooUrl = 'https://github.com/dege-diosg/dgVoodoo2/releases/download/2.87.6/dgVoodoo2_87_6.zip'
$DgVoodooSha256 = '9afa493396feec7108f42a2d97661eef96bbaac5addf0dfb5cfbc3001cd76a0a'
$Resolutions = '1152x720, 1280x800, 1440x900'   # extra modes added by the exe patch (index 1..3)
$DefaultMode = 2                                # 1280x800

Write-Host ''
Write-Host '  The Entente Gold - poprawka dla Windows 10/11 / Windows 10/11 fix' -ForegroundColor Cyan
Write-Host ''

$GameDir = Resolve-GameDir $GameDir
Say "Folder gry: $GameDir" "Game folder: $GameDir"
Stop-Game

$backup = Join-Path $GameDir $BackupDirName
$firstInstall = -not (Test-Path $backup)
New-Item -ItemType Directory -Force $backup | Out-Null

# 1. Antanta.exe ----------------------------------------------------------------------------
$patchFile = Join-Path $PSScriptRoot 'antanta.patch'
$patchLines = Get-Content $patchFile | Where-Object { $_ -and -not $_.StartsWith('#') }
$header = @{}
foreach ($l in $patchLines | Select-Object -First 3) { $k, $v = $l -split ' ', 2; $header[$k] = $v }
$exe = Join-Path $GameDir $GameExe
$hash = Get-Sha256 $exe
# Antanta.exe patched by an older release of this fix: start again from the backed-up original.
$olderReleases = @('d67bb7c604651aaabb1a9c8befbb31cf3393beab1cd53fee8cad90700e27550b',   # v1.0.0
                   '63f0395798b47fca1609fd7386f1748ce2528f2abca39496da99fa5b1a7c6ab6')   # v1.1.0
$savedOrig = Join-Path $backup $GameExe
if ($olderReleases -contains $hash -and (Test-Path $savedOrig) -and (Get-Sha256 $savedOrig) -eq $header['source-sha256']) {
    Copy-Item $savedOrig $exe -Force
    $hash = $header['source-sha256']
    Say 'Aktualizuje poprawke z poprzedniej wersji.' 'Updating the fix from a previous version.'
}
if ($hash -eq $header['target-sha256']) {
    Say 'Antanta.exe jest juz poprawiony.' 'Antanta.exe is already patched.'
} elseif ($hash -eq $header['source-sha256']) {
    Copy-Item $exe (Join-Path $backup $GameExe) -Force
    $bytes = [IO.File]::ReadAllBytes($exe)
    if ($bytes.Length -ne [int]$header['size']) { Fail 'Nieoczekiwany rozmiar Antanta.exe.' 'Unexpected Antanta.exe size.' }
    foreach ($l in $patchLines | Select-Object -Skip 3) {
        $off, $hex = $l -split ' '
        $o = [Convert]::ToInt32($off, 16)
        for ($i = 0; $i -lt $hex.Length; $i += 2) { $bytes[$o + $i / 2] = [Convert]::ToByte($hex.Substring($i, 2), 16) }
    }
    [IO.File]::WriteAllBytes($exe, $bytes)
    if ((Get-Sha256 $exe) -ne $header['target-sha256']) {
        Copy-Item (Join-Path $backup $GameExe) $exe -Force
        Fail 'Poprawka Antanta.exe nie powiodla sie (przywrocono oryginal).' 'Patching Antanta.exe failed (original restored).'
    }
    Say 'Poprawiono Antanta.exe (kopia oryginalu w _win11fix_backup).' 'Patched Antanta.exe (original saved in _win11fix_backup).' 'Green'
} else {
    Fail ('Nieznana wersja Antanta.exe. Jesli uzywales innych poprawek, w Steam kliknij prawym na gre -> ' +
          'Wlasciwosci -> Zainstalowane pliki -> Zweryfikuj spojnosc plikow, potem uruchom instalator ponownie.') `
         ('Unknown Antanta.exe version. If you used other fixes, in Steam right-click the game -> Properties -> ' +
          'Installed Files -> Verify integrity of game files, then run this installer again.')
}

# 2. dgVoodoo2 (DirectDraw/Direct3D 7 -> Direct3D 11) ------------------------------------------
# Files from other wrappers would conflict; on the first install move them into the backup folder
# (on a re-install these names are our own dgVoodoo files and are simply overwritten).
if ($firstInstall) {
    foreach ($f in 'ddraw.dll', 'D3DImm.dll', 'dgVoodoo.conf', 'wined3d.dll', 'dxwrapper.dll', 'dxwrapper.ini', 'DDrawCompat.ini') {
        $p = Join-Path $GameDir $f
        if (Test-Path $p) { Move-Item $p (Join-Path $backup $f) }
    }
}
$zip = Join-Path $PSScriptRoot 'dgVoodoo2_87_6.zip'          # optional offline copy next to the script
if (-not (Test-Path $zip)) {
    $zip = Join-Path $env:TEMP 'dgVoodoo2_87_6.zip'
    Say 'Pobieram dgVoodoo2 (ok. 9 MB) z GitHuba autora...' 'Downloading dgVoodoo2 (about 9 MB) from its author on GitHub...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try { Invoke-WebRequest -Uri $DgVoodooUrl -OutFile $zip -UseBasicParsing }
    catch { Fail 'Nie udalo sie pobrac dgVoodoo2 - sprawdz polaczenie z internetem.' 'Could not download dgVoodoo2 - check your internet connection.' }
}
if ((Get-Sha256 $zip) -ne $DgVoodooSha256) { Fail 'Pobrany plik dgVoodoo2 ma zla sume kontrolna.' 'The downloaded dgVoodoo2 file has a wrong checksum.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($zip)
try {
    foreach ($entry in $archive.Entries) {
        $target = switch ($entry.FullName) {
            'MS/x86/DDraw.dll'  { 'DDraw.dll' }
            'MS/x86/D3DImm.dll' { 'D3DImm.dll' }
            'dgVoodoo.conf'     { 'dgVoodoo.conf' }
            default             { $null }
        }
        if ($target) { [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $GameDir $target), $true) }
    }
} finally { $archive.Dispose() }
$conf = Join-Path $GameDir 'dgVoodoo.conf'
$settings = [ordered]@{
    ScalingMode                = 'stretched_ar'   # keep the aspect ratio, never stretch
    Resampling                 = 'bicubic'
    FullscreenAttributes       = 'fake'           # borderless full screen, safe Alt+Tab
    dgVoodooWatermark          = 'false'
    FastVideoMemoryAccess      = 'true'
    PrimarySurfaceBatchedUpdate = 'true'          # menus otherwise refresh only when the mouse moves
    ExtraEnumeratedResolutions = $Resolutions
}
$lines = Get-Content $conf | ForEach-Object {
    $line = $_
    foreach ($k in $settings.Keys) { if ($line -match "^\s*$k\s*=") { $line = $line -replace '=.*$', "= $($settings[$k])" } }
    $line
}
[IO.File]::WriteAllLines($conf, $lines, (New-Object Text.UTF8Encoding $false))
Say 'Zainstalowano dgVoodoo2.' 'Installed dgVoodoo2.' 'Green'

# 3. Sharp picture with Windows display scaling (125%, 150%, 175%...) --------------------------
$manifest = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
</assembly>
'@
[IO.File]::WriteAllText((Join-Path $GameDir 'Antanta.exe.manifest'), $manifest, (New-Object Text.UTF8Encoding $false))

# 4. Settings: widescreen resolution; skip the intro video that hangs on a black screen -------
$gameInf = Join-Path $GameDir 'Data\GameInf.txt'
if ((Test-Path $gameInf) -and -not (Test-Path (Join-Path $backup 'GameInf.txt'))) { Copy-Item $gameInf $backup }
Set-GameInfValue $GameDir 4 $DefaultMode
$videoInf = Join-Path $GameDir 'Media\Video.inf'
if (Test-Path $videoInf) {
    if (-not (Test-Path (Join-Path $backup 'Video.inf'))) { Copy-Item $videoInf $backup }
    [IO.File]::WriteAllBytes($videoInf, [byte[]]@())
}

Write-Host ''
Say 'GOTOWE! Uruchom gre normalnie ze Steama.' 'DONE! Start the game from Steam as usual.' 'Green'
Say 'Rozdzielczosc zmienisz w Opcjach (przytrzymaj przycisk zmiany): 1024x768, 1152x720, 1280x800, 1440x900.' `
    'Change resolution in Options (hold the change button): 1024x768, 1152x720, 1280x800, 1440x900.'
Write-Host ''
