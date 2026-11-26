#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Exercise install-user.ps1 in isolated temporary project roots and HOME.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'install-user.ps1'
$engine = (Get-Process -Id $PID).Path
$repoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$isWindowsLike = if ($null -ne $IsWindows) { [bool]$IsWindows } else { $env:OS -eq 'Windows_NT' }
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('skills-installer-test-' + [guid]::NewGuid())
$projectRoot = Join-Path $tempRoot 'project'
$outsideRoot = Join-Path $tempRoot 'outside'
$fakeHome = Join-Path $tempRoot 'home'
$savedHome = $env:HOME
$skillsRoot = $null

function Invoke-InstallerJson {
    param([string[]]$Arguments)
    $text = & $engine -NoProfile -ExecutionPolicy Bypass -File $installer @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Installer failed: $text" }
    return ($text | ConvertFrom-Json)
}

function Remove-TestLink {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Get-ChildItem -LiteralPath (Split-Path -Parent $Path) -Force | Where-Object Name -eq (Split-Path -Leaf $Path))) { return }
    if ($isWindowsLike) {
        & cmd.exe /d /c rmdir "`"$Path`"" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to remove test junction: $Path" }
    } else {
        Remove-Item -LiteralPath $Path -Force
    }
}

function New-TestLink {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Target)
    if ($isWindowsLike) { New-Item -ItemType Junction -Path $Path -Target $Target | Out-Null }
    else { New-Item -ItemType SymbolicLink -Path $Path -Target $Target | Out-Null }
}

try {
    New-Item -ItemType Directory -Path $projectRoot, $outsideRoot, $fakeHome | Out-Null

    # --- Project scope: agents only, never .claude ---
    $install = Invoke-InstallerJson @('-Scope', 'Project', '-ProjectRoot', $projectRoot, '-Json')
    if (-not $install.ok -or $install.mode -ne 'install') { throw 'Initial project installation did not succeed.' }

    $skillsRoot = Join-Path $projectRoot '.agents/skills'
    $claudeRoot = Join-Path $projectRoot '.claude/skills'
    if (@($install.targetRoots).Count -ne 1) { throw 'Project install must report exactly one target root.' }
    if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'grill-me/SKILL.md'))) { throw 'Project agents skill root was not populated.' }
    if (Test-Path -LiteralPath $claudeRoot) { throw 'Project install must not create .claude/skills.' }
    if (Test-Path -LiteralPath (Join-Path $skillsRoot 'make-dev-plan')) { throw 'Default project install must not link make-dev-plan.' }
    if (Test-Path -LiteralPath (Join-Path $skillsRoot 'plan-mode-plan-writer')) { throw 'Default project install must not link plan-mode-plan-writer.' }
    if ([int]$install.skillCount -ne 12) { throw "Default project install skillCount was $($install.skillCount), expected 12." }

    $compatInstall = Invoke-InstallerJson @('-Scope', 'Project', '-ProjectRoot', $projectRoot, '-IncludeCompat', '-Json')
    if (-not $compatInstall.ok -or -not $compatInstall.includeCompat) { throw 'IncludeCompat project installation did not succeed.' }
    if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'make-dev-plan/SKILL.md'))) { throw 'IncludeCompat did not link make-dev-plan.' }
    if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'plan-mode-plan-writer/SKILL.md'))) { throw 'IncludeCompat did not link plan-mode-plan-writer.' }
    if ([int]$compatInstall.skillCount -ne 14) { throw "IncludeCompat skillCount was $($compatInstall.skillCount), expected 14." }

    $defaultAgain = Invoke-InstallerJson @('-Scope', 'Project', '-ProjectRoot', $projectRoot, '-Json')
    if (-not $defaultAgain.ok) { throw 'Default reinstall after IncludeCompat failed.' }
    if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'make-dev-plan/SKILL.md'))) { throw 'Default reinstall pruned a previously installed compat alias.' }
    if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'plan-mode-plan-writer/SKILL.md'))) { throw 'Default reinstall pruned plan-mode-plan-writer.' }

    $outsideLink = Join-Path $skillsRoot 'eli5'
    Remove-TestLink $outsideLink
    New-TestLink $outsideLink $outsideRoot

    $staleOwned = Join-Path $skillsRoot 'stale-owned'
    New-TestLink $staleOwned (Join-Path $repoRoot 'grill-me')
    $realDirectory = Join-Path $skillsRoot 'real-directory'
    New-Item -ItemType Directory -Path $realDirectory | Out-Null

    $broken = Join-Path $skillsRoot 'user-broken'
    New-TestLink $broken (Join-Path $tempRoot 'missing-target')
    $wrongKnown = Join-Path $skillsRoot 'plan-plain'
    Remove-TestLink $wrongKnown
    New-TestLink $wrongKnown (Join-Path $repoRoot 'eli5')
    $partialText = & $engine -NoProfile -File $installer -Scope Project -ProjectRoot $projectRoot -Json
    if ($LASTEXITCODE -ne 2) { throw 'Conflicting installation must return partial exit 2.' }
    $partial = $partialText | ConvertFrom-Json
    if ($partial.ok -or $partial.conflictCount -lt 2) { throw 'Conflicts were reported as full success.' }
    if (-not (Test-Path -LiteralPath $staleOwned)) { throw 'Install pruned custom alias.' }
    if (-not (Get-Item -LiteralPath $broken -Force).LinkType) { throw 'Broken custom alias removed.' }
    $brokenKnown=Join-Path $skillsRoot 'brainstorming'
    Remove-TestLink $brokenKnown
    New-TestLink $brokenKnown (Join-Path $tempRoot 'missing-known-target')
    $realKnown=Join-Path $skillsRoot 'audio-transcribe'
    Remove-TestLink $realKnown
    New-Item -ItemType Directory $realKnown | Out-Null
    'synthetic user file' | Set-Content (Join-Path $realKnown 'keep.txt')
    $partialText = & $engine -NoProfile -File $installer -Scope Project -ProjectRoot $projectRoot -Json
    if ($LASTEXITCODE -ne 2 -or ($partialText | ConvertFrom-Json).ok) { throw 'Known broken/real conflicts must not report success.' }
    $preview = Invoke-InstallerJson @('-Scope', 'Project', '-ProjectRoot', $projectRoot, '-Remove', '-DryRun', '-Json')
    if (-not $preview.ok -or $preview.mode -ne 'remove' -or $preview.removedCount -lt 1) { throw 'Remove dry-run did not report checkout-owned links.' }
    if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'grill-me'))) { throw 'Remove dry-run mutated an installed link.' }
    if (-not (Test-Path -LiteralPath $staleOwned)) { throw 'Remove dry-run mutated a stale checkout-owned link.' }

    $removed = Invoke-InstallerJson @('-Scope', 'Project', '-ProjectRoot', $projectRoot, '-Remove', '-Json')
    if (-not $removed.ok -or $removed.mode -ne 'remove' -or $removed.removedCount -lt 1) { throw 'Remove mode did not report removed links.' }
    if (Test-Path -LiteralPath (Join-Path $skillsRoot 'grill-me')) { throw 'Checkout-owned installed link was not removed.' }
    if (-not (Test-Path -LiteralPath $wrongKnown)) { throw 'Changed known target was removed.' }
    if (-not (Get-Item -LiteralPath $broken -Force).LinkType) { throw 'Broken alias was removed.' }
    if (-not (Test-Path -LiteralPath $staleOwned)) { throw 'User-created alias was removed.' }
    $outsideItem = Get-ChildItem -LiteralPath $skillsRoot -Force | Where-Object Name -eq 'eli5' | Select-Object -First 1
    if (-not $outsideItem -or $null -eq $outsideItem.LinkType) { throw 'Outside-checkout link was removed or replaced.' }
    if (-not (Test-Path -LiteralPath $realDirectory)) { throw 'Real directory was removed.' }
    if (-not (Get-Item -LiteralPath $brokenKnown -Force).LinkType) { throw 'Known broken link was removed.' }
    if ((Get-Content (Join-Path $realKnown 'keep.txt') -Raw) -notmatch 'synthetic user file') { throw 'Known real directory changed.' }

    $again = Invoke-InstallerJson @('-Scope', 'Project', '-ProjectRoot', $projectRoot, '-Remove', '-Json')
    if (-not $again.ok -or $again.removedCount -ne 0) { throw 'Repeated remove was not idempotent.' }

    $projectClaudeReject = & $engine -NoProfile -ExecutionPolicy Bypass -File $installer -Scope Project -ProjectRoot $projectRoot -IncludeClaude -Json
    if ($LASTEXITCODE -eq 0) { throw 'Project + IncludeClaude should fail.' }
    $rejectJson = $projectClaudeReject | ConvertFrom-Json
    if ($rejectJson.ok -or ($rejectJson.error -notmatch 'IncludeClaude')) { throw 'Project + IncludeClaude did not report the expected error.' }

    # A linked target-root parent is rejected before any write outside it.
    $linkedProject=Join-Path $tempRoot 'linked-project'
    New-Item -ItemType Directory $linkedProject | Out-Null
    New-TestLink (Join-Path $linkedProject '.agents') $outsideRoot
    $linkedResult = & $engine -NoProfile -File $installer -Scope Project -ProjectRoot $linkedProject -Json
    if ($LASTEXITCODE -eq 0 -or ($linkedResult | ConvertFrom-Json).ok) { throw 'Linked installation root should fail.' }
    if (Test-Path (Join-Path $outsideRoot 'skills')) { throw 'Linked installation root wrote outside.' }

    # --- User scope under a fake HOME ---
    $env:HOME = $fakeHome
    $userAgents = Join-Path $fakeHome '.agents/skills'
    $userClaude = Join-Path $fakeHome '.claude/skills'

    $userDefault = Invoke-InstallerJson @('-Scope', 'User', '-Json')
    if (-not $userDefault.ok) { throw 'User default install failed.' }
    if (@($userDefault.targetRoots).Count -ne 1) { throw 'User default must install only ~/.agents/skills.' }
    if (-not (Test-Path -LiteralPath (Join-Path $userAgents 'grill-me/SKILL.md'))) { throw 'User agents root was not populated.' }
    if (Test-Path -LiteralPath (Join-Path $userAgents 'make-dev-plan')) { throw 'User default must not link make-dev-plan.' }
    if (Test-Path -LiteralPath $userClaude) { throw 'User default must not create ~/.claude/skills.' }
    if (-not $userDefault.events[0].root) { throw 'Installer events must include root.' }

    $userClaudeInstall = Invoke-InstallerJson @('-Scope', 'User', '-IncludeClaude', '-Json')
    if (-not $userClaudeInstall.ok) { throw 'User IncludeClaude install failed.' }
    if (@($userClaudeInstall.targetRoots).Count -ne 2) { throw 'User IncludeClaude must report two target roots.' }
    if (-not (Test-Path -LiteralPath (Join-Path $userClaude 'grill-me/SKILL.md'))) { throw 'User Claude root was not populated.' }

    $userRemoveAgentsOnly = Invoke-InstallerJson @('-Scope', 'User', '-Remove', '-Json')
    if (-not $userRemoveAgentsOnly.ok) { throw 'User remove without IncludeClaude failed.' }
    if (Test-Path -LiteralPath (Join-Path $userAgents 'grill-me')) { throw 'User remove did not clear agents links.' }
    if (-not (Test-Path -LiteralPath (Join-Path $userClaude 'grill-me'))) { throw 'User remove without IncludeClaude must leave Claude links.' }

    $userRemoveClaude = Invoke-InstallerJson @('-Scope', 'User', '-IncludeClaude', '-Remove', '-Json')
    if (-not $userRemoveClaude.ok -or $userRemoveClaude.removedCount -lt 1) { throw 'User Remove -IncludeClaude did not clear Claude links.' }
    if (Test-Path -LiteralPath (Join-Path $userClaude 'grill-me')) { throw 'Claude checkout-owned link was not removed.' }

    Write-Host '[test-install-user] PASS' -ForegroundColor Green
    exit 0
} catch {
    Write-Host "[test-install-user] FAIL: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    $env:HOME = $savedHome
    if ($skillsRoot -and (Test-Path -LiteralPath $skillsRoot)) { Remove-TestLink (Join-Path $skillsRoot 'eli5') }
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
