# Installs the Windows 10/11 fix for The Entente Gold (Steam).
# Started by Install.cmd (or Install-Improvements.cmd, which adds -Improvements: mouse-wheel zoom);
# can also be run as: install.ps1 [-GameDir "<folder with Antanta.exe>"] [-Improvements]
param([string]$GameDir, [switch]$Improvements)

. (Join-Path $PSScriptRoot 'common.ps1')

$DgVoodooUrl = 'https://github.com/dege-diosg/dgVoodoo2/releases/download/2.87.6/dgVoodoo2_87_6.zip'
$DgVoodooSha256 = '9afa493396feec7108f42a2d97661eef96bbaac5addf0dfb5cfbc3001cd76a0a'
$Resolutions = '1152x720, 1280x800, 1440x900'   # extra modes added by the exe patch (index 1..3)
$DefaultMode = 2                                # 1280x800
if ($Improvements) {
    # the map is drawn in 1920x1200 so that it can be zoomed out; it starts zoomed to the 1280x800 view
    $Resolutions = '1152x720, 1280x800, 1920x1200'
    $DefaultMode = 3
}
$ModeList = '1024x768, ' + $Resolutions

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
function Read-Patch($name) {
    $lines = @(Get-Content (Join-Path $PSScriptRoot $name) | Where-Object { $_ -and -not $_.StartsWith('#') })
    $head = @{}
    foreach ($l in $lines | Select-Object -First 3) { $k, $v = $l -split ' ', 2; $head[$k] = $v }
    @{ Lines = $lines; Header = $head }
}
$basic = Read-Patch 'antanta.patch'
$withZoom = Read-Patch 'antanta-improvements.patch'
$chosen = if ($Improvements) { $withZoom } else { $basic }
$patchLines, $header = $chosen.Lines, $chosen.Header
$exe = Join-Path $GameDir $GameExe
$hash = Get-Sha256 $exe
# Antanta.exe patched by an older release of this fix: start again from the backed-up original.
$olderReleases = @('d67bb7c604651aaabb1a9c8befbb31cf3393beab1cd53fee8cad90700e27550b',   # v1.0.0
                   '63f0395798b47fca1609fd7386f1748ce2528f2abca39496da99fa5b1a7c6ab6',   # v1.1.0
                   '0a27c9df159ff9b38f07275ea19ae92983f63983cb86082139d981a1a5d209ae',   # v1.2.0 pre-release build
                   '9e43eaf544d6521ce72d8038c96e6827670cd8129949acc50d738c16c2b64064',   # v1.2.0 pre-release build 2
                   'd4f55e2357d9df8293f3d24acd550c5118322e0ba31a64f3c15511ed4243c837',   # v1.2.0
                   '7f8255f7b388eb4ecdf9ac2e97eee3edf3fd76bec4809c337b994fd0e8d6eef1',   # main after PR #4 (unreleased)
                   'de66192cd204e5ee9fd540ac475ee7c855f1ec0511f2f7a684cad00a8cb9008b',   # 1440x900 load fix, first build
                   '1190c8b507c4cd38a2e60f1c6a18609a156bca60bb91b1a33432f3754c082f7f',   # improvements, first build (zoom in only)
                   '9d3bb2dd509574ac75a95ae32909b47dd80dc7613e6638532b12470ac129e86d',   # v1.3.0
                   'ec86c6adbd32c9ac7c9fe3b8b8fb55eaf38b40e3d2264f25e98d254b3bf14cd1',   # v1.3.0 with improvements
                   '02f103b91ce6346b6d12a3b7e596992dab25855d4a005bc56e5c56a8c035be3d',   # main after PR #7 (unreleased)
                   '05dbcc4048f094787e1447d7bd27483ace56ba906c996ec75872cc93d54949b3',   # main after PR #7 with improvements
                   '728017e8bfc5132e89460b99e3ab237695ac515789fab6930897e7c626b993f1',   # PR #8 (tips overlay)
                   'eee2e6d1de2147f65b2da28330f680fdbe7f4f7e3f5f1181cf080c809dac1346',   # PR #8 with improvements
                   '13ef3a69307fcf0c930ebd010a21c69f75c4516be688adecbb03eb1c2bb95c36',   # PR #9 (scroll pace)
                   '274ba786b18062a682c9c84f58ca869f3eb4bfdf9e50b2632d66eb8c14ac402a',   # PR #9 with improvements
                   '96ff902e53891dfaed776a308239c15fbc3cbdd943d2295b65e57c29b5f08ccf',   # v1.3.1 with improvements
                   '7a884e70fde9a6668f3fc625af6f836840a99fddc560847b5a63f7b8698512de',   # v1.3.2 with improvements
                   '330f14e92be48949d33c35fb48348c1c865ddab9da47a89672d01f074a6b80b7',   # v1.3.1 - v1.3.2
                   'c80af57138dfe60cc69cda1bff2040779f1f907ad158d91f64dfb48f94b52559',   # main after PR #12 with improvements
                   '169854534e57101c0514896ee22528ca0d7a5235e075fd8cfacf35fff0964df8',   # PR #13 with improvements
                   'b3386c9b7620798c55d4289252db4f61557f9cc596dac25611f26b9871990c60',   # PR #14 with improvements
                   '17abcd732cd94a2fe2cac5833363f7aec394a6432e73e2bea21028c1e3c54984',   # v1.3.3 with improvements
                   'e1353d5a10a0df0ebf5551e6a4925d9a9ab8d90290b3400539bdf6cf0703db45',   # v1.3.3
                   '53b9c91d78377becfe1a8fece01a9073a6425c141ee3b366e2443c0ff2587484')   # main after PR #17 with improvements
# switching between the basic fix and the one with improvements also starts from the original
$olderReleases += @($basic.Header['target-sha256'], $withZoom.Header['target-sha256']) | Where-Object { $_ -ne $header['target-sha256'] }
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
Say "Rozdzielczosc zmienisz w Opcjach (przytrzymaj przycisk zmiany): $ModeList." `
    "Change resolution in Options (hold the change button): $ModeList."
if ($Improvements) {
    Say 'Ulepszenia: kolko myszy oraz klawisze + i - oddalaja mape (do 1,5x szerszego widoku) i przyblizaja ja (do 2,5x).' `
        'Improvements: the mouse wheel and the + / - keys zoom the map out (up to a 1.5x wider view) and in (up to 2.5x).'
    Say 'Mapa bez ramki, zasoby i energia na polprzezroczystym pasku u gory.' `
        'The map without the frame; resources and electricity on a semi-transparent top bar.'
}
Write-Host ''
