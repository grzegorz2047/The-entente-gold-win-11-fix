# Removes the fix and restores the files saved by install.ps1.
param([string]$GameDir)

. (Join-Path $PSScriptRoot 'common.ps1')

Write-Host ''
Write-Host '  The Entente Gold - usuwanie poprawki / removing the fix' -ForegroundColor Cyan
Write-Host ''

$GameDir = Resolve-GameDir $GameDir
Say "Folder gry: $GameDir" "Game folder: $GameDir"
Stop-Game

$backup = Join-Path $GameDir $BackupDirName
if (-not (Test-Path $backup)) { Fail 'Nie znaleziono kopii zapasowej - poprawka nie byla instalowana.' 'No backup found - the fix was not installed.' }

foreach ($f in 'DDraw.dll', 'D3DImm.dll', 'dgVoodoo.conf', 'Antanta.exe.manifest') {
    Remove-Item (Join-Path $GameDir $f) -Force -ErrorAction SilentlyContinue
}
$restore = @{ 'Antanta.exe' = $GameExe; 'GameInf.txt' = 'Data\GameInf.txt'; 'Video.inf' = 'Media\Video.inf' }
Get-ChildItem $backup -File | ForEach-Object {
    $rel = if ($restore.ContainsKey($_.Name)) { $restore[$_.Name] } else { $_.Name }   # other wrappers' files go back to the root
    Copy-Item $_.FullName (Join-Path $GameDir $rel) -Force
}
Remove-Item $backup -Recurse -Force

Write-Host ''
Say 'Przywrocono oryginalne pliki gry.' 'The original game files have been restored.' 'Green'
Write-Host ''
