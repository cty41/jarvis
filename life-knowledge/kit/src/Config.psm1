Set-StrictMode -Version Latest

function Get-KbProfilePath {
    if ($env:LIFE_KNOWLEDGE_PROFILE) { return [IO.Path]::GetFullPath($env:LIFE_KNOWLEDGE_PROFILE) }
    Join-Path $HOME '.config\life-knowledge\profile.json'
}

function Read-KbJson {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { throw "Invalid JSON: $Path. $($_.Exception.Message)" }
}

function Write-KbJson {
    param([Parameter(Mandatory)]$Value,[Parameter(Mandatory)][string]$Path)
    $Path = Assert-KbStoragePath $Path
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Resolve-KbVaultPath {
    param([string]$ExplicitPath)
    if ($ExplicitPath) { return [IO.Path]::GetFullPath($ExplicitPath) }
    $profile = Read-KbJson (Get-KbProfilePath)
    if ($profile -and $profile.vaultPath) { return [IO.Path]::GetFullPath([string]$profile.vaultPath) }
    if ($env:LIFE_KNOWLEDGE_HOME) { return [IO.Path]::GetFullPath($env:LIFE_KNOWLEDGE_HOME) }
    return $null
}

function Assert-KbStoragePath {
    param([Parameter(Mandatory)][string]$Path,[switch]$MustExist)
    if (($Path -split '[\\/]') -contains '..') { throw 'Parent traversal is not allowed in storage paths.' }
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    $pack = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Linked/reparse storage path refused: $cursor" }
        if ((Test-Path -LiteralPath (Join-Path $cursor '.git')) -or
            (Test-Path -LiteralPath (Join-Path $cursor '.hg')) -or
            (Test-Path -LiteralPath (Join-Path $cursor '.svn')) -or
            (Test-Path -LiteralPath (Join-Path $cursor 'SKILL.md')) -or $cursor -eq $pack -or
            ((Test-Path -LiteralPath (Join-Path $cursor 'HEAD')) -and (Test-Path -LiteralPath (Join-Path $cursor 'objects')) -and (Test-Path -LiteralPath (Join-Path $cursor 'refs')))) {
            throw "Code repository/skill storage refused: $cursor"
        }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    if ($MustExist -and -not (Test-Path -LiteralPath $full)) { throw "Storage path is unavailable: $full" }
    return $full
}

function Assert-KbTreeSafe {
    param([Parameter(Mandatory)][string]$Path)
    $null = Assert-KbStoragePath $Path -MustExist
    foreach ($entry in @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)) {
        $null = Assert-KbStoragePath $entry.FullName
    }
}

function Assert-KbManagedClean {
    param([Parameter(Mandatory)][string]$Managed)
    Assert-KbTreeSafe $Managed
    $lockPath = Join-Path $Managed 'kit-lock.json'
    $lock = Read-KbJson $lockPath
    if (-not $lock -or -not $lock.managedFilesChecksum -or (Get-KbFileTreeHash $Managed) -ne [string]$lock.managedFilesChecksum) {
        throw 'Managed drift or invalid/missing lock; no files overwritten.'
    }
}

function Assert-KbPathWithin {
    param([Parameter(Mandatory)][string]$Root,[Parameter(Mandatory)][string]$Path)
    $separators = [char[]]@([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)
    $rootFull = (Assert-KbStoragePath $Root -MustExist).TrimEnd($separators) + [IO.Path]::DirectorySeparatorChar
    $pathFull = Assert-KbStoragePath $Path
    $comparison = if ($env:OS -eq 'Windows_NT') { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    if (-not $pathFull.StartsWith($rootFull, $comparison)) { throw "Path escapes vault boundary: $pathFull" }
    return $pathFull
}

function Get-KbFileTreeHash {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Assert-KbTreeSafe $Path
    $lines = Get-ChildItem -LiteralPath $Path -Recurse -File -Force |
        Where-Object { $_.Name -ne 'kit-lock.json' -and $_.FullName -notmatch '[\\/]runtime-data[\\/]' } |
        Sort-Object FullName | ForEach-Object {
            $rel = [IO.Path]::GetRelativePath([IO.Path]::GetFullPath($Path), $_.FullName)
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            "$rel`t$hash"
        }
    $text = [string]::Join("`n", $lines)
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','')) }
    finally { $sha.Dispose() }
}

Export-ModuleMember -Function Get-KbProfilePath,Read-KbJson,Write-KbJson,Resolve-KbVaultPath,Assert-KbPathWithin,Assert-KbStoragePath,Assert-KbTreeSafe,Assert-KbManagedClean,Get-KbFileTreeHash
