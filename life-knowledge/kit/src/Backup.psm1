Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Reports.psm1')
Import-Module (Join-Path $PSScriptRoot 'Config.psm1')

function Invoke-KbBackup {
    param([Parameter(Mandatory)][string]$VaultPath,[Parameter(Mandatory)][string]$Destination,[switch]$DryRun)
    if(-not (Test-Path -LiteralPath $VaultPath)){throw "Vault not found: $VaultPath"}
    $VaultPath=Assert-KbStoragePath $VaultPath -MustExist
    Assert-KbTreeSafe $VaultPath
    $Destination=Assert-KbStoragePath $Destination
    $relative=[IO.Path]::GetRelativePath($VaultPath,$Destination)
    if($relative -eq '.' -or ($relative -ne '..' -and -not $relative.StartsWith('..' + [IO.Path]::DirectorySeparatorChar) -and -not [IO.Path]::IsPathRooted($relative))){throw 'Backup destination must not be the source or inside it.'}
    $stamp=[guid]::NewGuid().ToString('N')
    $target=Join-Path $Destination "LifeKnowledge-$stamp"
    if(Test-Path -LiteralPath $target){throw "Backup target already exists: $target"}
    $changes=@("copy full plaintext vault $VaultPath -> $target (not encrypted)")
    if($DryRun){return (New-KbResult -Command 'backup' -Status 'dry-run' -State 'HEALTHY' -VaultPath $VaultPath -Changes $changes)}
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -LiteralPath $VaultPath -Destination $target -Recurse
    New-KbResult -Command 'backup' -Status 'ok' -State 'HEALTHY' -VaultPath $VaultPath -Changes $changes -Data @{backupPath=$target}
}

Export-ModuleMember -Function Invoke-KbBackup
