#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Link the default public skills into a user or project skill root.

.DESCRIPTION
    User scope (the default) installs into ~/.agents/skills (Cursor, Codex,
    OpenCode). Pass -IncludeClaude to also install into ~/.claude/skills
    (Claude Code). Cursor reads both roots, so Claude is opt-in to avoid
    duplicate skills. Project scope always installs only into
    <project>/.agents/skills, using -ProjectRoot or the nearest .git ancestor.
    Windows uses directory junctions; macOS/Linux use symbolic links.

    By default the two deprecated plan aliases (make-dev-plan,
    plan-mode-plan-writer) are not installed. Pass -IncludeCompat to add them.
    A later default install does not prune already installed compat links that
    still point into this checkout.

    The installer is idempotent and never replaces a real directory/file or a
    link owned by another checkout. It preserves unknown aliases and conflicting/broken links. -Remove only removes
    known manifest names whose exact target matches this checkout; no broad prune.
    It removes those recognized links
    in the selected roots (include -IncludeClaude to remove Claude-root links).
#>
[CmdletBinding()]
param(
    [ValidateSet('User', 'Project')]
    [string]$Scope = 'User',
    [string]$ProjectRoot,
    [switch]$IncludeClaude,
    [switch]$IncludeCompat,
    [switch]$Remove,
    [switch]$DryRun,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$events = [System.Collections.Generic.List[object]]::new()

function Test-WindowsLike {
    if ($null -ne $IsWindows) { return [bool]$IsWindows }
    return $env:OS -eq 'Windows_NT'
}

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path, [string]$BasePath)
    if (-not [System.IO.Path]::IsPathRooted($Path) -and $BasePath) {
        $Path = Join-Path $BasePath $Path
    }
    return [System.IO.Path]::GetFullPath($Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
}

function Test-OwnedSkillLink {
    param([string]$Name,[string]$Target)
    if ($knownPackSkills -cnotcontains $Name) { return $false }
    $expected = Get-NormalizedPath (Join-Path $repoRoot $Name)
    $comparison = if (Test-WindowsLike) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    return $Target.Equals($expected, $comparison) -and (Test-Path -LiteralPath $Target -PathType Container)
}

function Assert-UnlinkedAncestors {
    param([string]$Path)
    $cursor = Get-NormalizedPath $Path
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Linked installation root/ancestor refused: $cursor" }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Add-Event {
    param([string]$Action, [string]$Name, [string]$Path, [string]$Target, [string]$Reason, [string]$Root)
    $event = [ordered]@{ action = $Action; name = $Name; path = $Path }
    if ($Root) { $event.root = $Root }
    if ($Target) { $event.target = $Target }
    if ($Reason) { $event.reason = $Reason }
    $events.Add([pscustomobject]$event)
    if (-not $Json) {
        $label = ('[{0,-5}]' -f $Action)
        $detail = if ($Reason) { "$Name ($Reason)" } elseif ($Target) { "$Name -> $Target" } else { $Name }
        if ($Root) { $detail = "$detail @ $Root" }
        Write-Host "$label $detail"
    }
}

function Remove-SkillLink {
    param([Parameter(Mandatory)][string]$Path)
    if ($DryRun) { return }
    if (Test-WindowsLike) {
        & cmd.exe /d /c rmdir "`"$Path`""
        if ($LASTEXITCODE -ne 0) { throw "Failed to remove junction: $Path" }
    } else {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Find-ProjectRoot {
    param([string]$ExplicitRoot)
    if ($ExplicitRoot) {
        return (Resolve-Path -LiteralPath $ExplicitRoot -ErrorAction Stop).Path
    }
    $cursor = (Get-Location).ProviderPath
    while ($cursor) {
        if (Test-Path -LiteralPath (Join-Path $cursor '.git')) { return $cursor }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    throw 'Project scope requires -ProjectRoot or a current directory beneath a .git project.'
}

function Get-InstallManifest {
    $path = Join-Path $PSScriptRoot 'install-skills.json'
    if (-not (Test-Path -LiteralPath $path)) { throw "Install manifest missing: $path" }
    return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Get-PackSkillDirectories {
    param(
        [Parameter(Mandatory)]$Manifest,
        [bool]$WithCompat
    )
    $wanted = [System.Collections.Generic.List[string]]::new()
    foreach ($name in @($Manifest.defaultSkills)) { [void]$wanted.Add([string]$name) }
    if ($WithCompat) {
        foreach ($name in @($Manifest.compatSkills)) { [void]$wanted.Add([string]$name) }
    }
    $dirs = foreach ($name in $wanted) {
        $dir = Join-Path $repoRoot $name
        if (-not (Test-Path -LiteralPath (Join-Path $dir 'SKILL.md'))) {
            throw "Manifest skill not found in repository root: $name"
        }
        Get-Item -LiteralPath $dir
    }
    return @($dirs | Sort-Object Name)
}

function Get-KnownPackSkillNames {
    param([Parameter(Mandatory)]$Manifest)
    return @(@($Manifest.defaultSkills) + @($Manifest.compatSkills) | ForEach-Object { [string]$_ })
}

function Get-SkillTargetRoots {
    param(
        [Parameter(Mandatory)][string]$Base,
        [Parameter(Mandatory)][string]$ScopeName,
        [bool]$WithClaude
    )
    $roots = [System.Collections.Generic.List[string]]::new()
    $roots.Add((Join-Path (Join-Path $Base '.agents') 'skills'))
    if ($ScopeName -eq 'User' -and $WithClaude) {
        $roots.Add((Join-Path (Join-Path $Base '.claude') 'skills'))
    }
    return @($roots)
}

try {
    if ($Scope -eq 'User' -and $ProjectRoot) {
        throw '-ProjectRoot is only valid with -Scope Project.'
    }
    if ($Scope -eq 'Project' -and $IncludeClaude) {
        throw '-IncludeClaude is only valid with -Scope User.'
    }
    $resolvedProjectRoot = $null
    $userHome = if (-not [string]::IsNullOrWhiteSpace($env:HOME)) { $env:HOME } else { $HOME }
    $base = if ($Scope -eq 'Project') { $resolvedProjectRoot = Find-ProjectRoot $ProjectRoot; $resolvedProjectRoot } else { $userHome }
    $skillsDirs = Get-SkillTargetRoots -Base $base -ScopeName $Scope -WithClaude ([bool]$IncludeClaude)

    $manifest = Get-InstallManifest
    $knownPackSkills = @(Get-KnownPackSkillNames -Manifest $manifest)
    foreach ($root in $skillsDirs) { Assert-UnlinkedAncestors $root }
    if ($Remove) {
        foreach ($skillsDir in $skillsDirs) {
            if (Test-Path -LiteralPath $skillsDir) {
                Get-ChildItem -LiteralPath $skillsDir -Force | ForEach-Object {
                    if ($null -eq $_.LinkType) {
                        Add-Event 'skip' $_.Name $_.FullName '' 'existing item is not a link' $skillsDir
                        return
                    }
                    $rawTarget = ($_.Target -join '')
                    $target = Get-NormalizedPath $rawTarget (Split-Path -Parent $_.FullName)
                    if (Test-OwnedSkillLink -Name $_.Name -Target $target) {
                        Add-Event 'remove' $_.Name $_.FullName $target 'checkout-owned link' $skillsDir
                        Remove-SkillLink $_.FullName
                    } else {
                        Add-Event 'skip' $_.Name $_.FullName $target 'link target is outside this checkout' $skillsDir
                    }
                }
            }
        }

        $result = [ordered]@{
            ok = $true
            mode = 'remove'
            scope = $Scope
            projectRoot = $resolvedProjectRoot
            includeClaude = [bool]$IncludeClaude
            targetRoots = @($skillsDirs)
            dryRun = [bool]$DryRun
            removedCount = @($events | Where-Object { $_.action -eq 'remove' }).Count
            events = @($events)
        }
        if ($Json) { $result | ConvertTo-Json -Depth 6 } else { Write-Host "`n[done ] checkout-owned skill link(s) removed from $($skillsDirs -join ', ')" -ForegroundColor Green }
        exit 0
    }

    $manifest = Get-InstallManifest
    $skills = @(Get-PackSkillDirectories -Manifest $manifest -WithCompat ([bool]$IncludeCompat))
    $knownPackSkills = @(Get-KnownPackSkillNames -Manifest $manifest)
    if ($skills.Count -eq 0) { throw 'No installable skills found in the install manifest.' }

    foreach ($skillsDir in $skillsDirs) {
        if (-not (Test-Path -LiteralPath $skillsDir)) {
            Add-Event 'mkdir' '' $skillsDir '' 'skill root missing' $skillsDir
            if (-not $DryRun) { New-Item -ItemType Directory -Path $skillsDir -Force | Out-Null }
        }

        $existingByName = @{}
        if (Test-Path -LiteralPath $skillsDir) {
            Get-ChildItem -LiteralPath $skillsDir -Force | ForEach-Object { $existingByName[$_.Name] = $_ }
        }

        foreach ($skill in $skills) {
            $linkPath = Join-Path $skillsDir $skill.Name
            $existing = $existingByName[$skill.Name]
            if ($existing) {
                if ($null -eq $existing.LinkType) {
                    Add-Event 'conflict' $skill.Name $linkPath '' 'existing item is not a link' $skillsDir
                    continue
                }
                $rawTarget = ($existing.Target -join '')
                $target = Get-NormalizedPath $rawTarget (Split-Path -Parent $existing.FullName)
                $expected = Get-NormalizedPath $skill.FullName
                $comparison = if (Test-WindowsLike) { [System.StringComparison]::OrdinalIgnoreCase } else { [System.StringComparison]::Ordinal }
                if ($target.Equals($expected, $comparison) -and (Test-Path -LiteralPath $target -PathType Container)) {
                    Add-Event 'keep' $skill.Name $linkPath $target '' $skillsDir
                    continue
                }
                Add-Event 'conflict' $skill.Name $linkPath $target 'unowned, changed or broken link preserved' $skillsDir
                continue
            }

            Add-Event 'link' $skill.Name $linkPath $skill.FullName '' $skillsDir
            if (-not $DryRun) {
                if (Test-WindowsLike) {
                    New-Item -ItemType Junction -Path $linkPath -Target $skill.FullName | Out-Null
                } else {
                    New-Item -ItemType SymbolicLink -Path $linkPath -Target $skill.FullName | Out-Null
                }
            }
        }

        # Unknown names are never pruned, even when they target this checkout.
    }
    $conflicts = @($events | Where-Object action -eq 'conflict').Count

    $result = [ordered]@{
        ok = ($conflicts -eq 0)
        conflictCount = $conflicts
        mode = 'install'
        scope = $Scope
        projectRoot = $resolvedProjectRoot
        includeClaude = [bool]$IncludeClaude
        includeCompat = [bool]$IncludeCompat
        targetRoots = @($skillsDirs)
        dryRun = [bool]$DryRun
        skillCount = $skills.Count
        events = @($events)
    }
    if ($Json) { $result | ConvertTo-Json -Depth 6 } else { Write-Host "`n[done ] requested=$($skills.Count) conflicts=$conflicts (inspect events)" }
    if ($conflicts -gt 0) { exit 2 }
    exit 0
} catch {
    if ($Json) {
        [ordered]@{ ok = $false; scope = $Scope; dryRun = [bool]$DryRun; includeClaude = [bool]$IncludeClaude; includeCompat = [bool]$IncludeCompat; error = $_.Exception.Message; events = @($events) } | ConvertTo-Json -Depth 6
    } else {
        Write-Host "[error] $($_.Exception.Message)" -ForegroundColor Red
    }
    exit 1
}
