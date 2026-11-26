BeforeAll {
    $script:oldProfile=$env:LIFE_KNOWLEDGE_PROFILE
    $env:LIFE_KNOWLEDGE_PROFILE=Join-Path $TestDrive 'profile.json'
    $script:kit=Split-Path -Parent $PSScriptRoot
    foreach($module in @('Config','Init','Upgrade','Migration','Backup','Doctor','PrivacyScan')) {
        Import-Module (Join-Path $script:kit "src/$module.psm1") -Force
    }
    function New-FixtureVault([string]$Name) {
        $path=Join-Path $TestDrive $Name
        Invoke-KbInit $path $script:kit | Out-Null
        return $path
    }
    function New-FixtureLink([string]$Path,[string]$Target) {
        $kind=if($env:OS -eq 'Windows_NT'){'Junction'}else{'SymbolicLink'}
        New-Item -ItemType $kind -Path $Path -Target $Target | Out-Null
    }
}
AfterAll {$env:LIFE_KNOWLEDGE_PROFILE=$script:oldProfile}

Describe 'Storage boundary safety' {
    It 'rejects .git directory and worktree .git file roots before init' {
        foreach($name in @('gitdir','gitfile')) {
            $vault=Join-Path $TestDrive $name
            New-Item -ItemType Directory $vault | Out-Null
            if($name -eq 'gitdir'){New-Item -ItemType Directory (Join-Path $vault '.git') | Out-Null}
            else{'gitdir: unused' | Set-Content (Join-Path $vault '.git')}
            {Invoke-KbInit $vault $script:kit} | Should -Throw
            Test-Path (Join-Path $vault '00_System') | Should -BeFalse
        }
    }
    It 'rejects a linked vault root without changing its target' {
        $outside=Join-Path $TestDrive 'outside-root'; New-Item -ItemType Directory $outside | Out-Null
        $link=Join-Path $TestDrive 'linked-vault'; New-FixtureLink $link $outside
        {Invoke-KbInit $link $script:kit} | Should -Throw
        @(Get-ChildItem -LiteralPath $outside).Count | Should -Be 0
    }
    It 'rejects ingest through a directory link to outside' {
        $vault=New-FixtureVault 'ingest-vault'
        $outside=Join-Path $TestDrive 'outside-ingest'; New-Item -ItemType Directory $outside | Out-Null
        New-FixtureLink (Join-Path $vault 'link') $outside
        $source=Join-Path $TestDrive 'input.txt'; 'fixture' | Set-Content $source
        {Invoke-KbIngest $vault $source 'link/new.txt'} | Should -Throw
        Test-Path (Join-Path $outside 'new.txt') | Should -BeFalse
    }
    It 'rejects archive traversal even when the result remains inside the vault' {
        $vault=New-FixtureVault 'archive-vault'
        {Invoke-KbArchive $vault '../README.md'} | Should -Throw
        Test-Path (Join-Path $vault 'README.md') | Should -BeTrue
    }
    It 'archives a normal project slug into the expected subtree' {
        $vault=New-FixtureVault 'normal-archive'
        Invoke-KbNewProject $vault 'fixture-project' | Out-Null
        Invoke-KbArchive $vault 'fixture-project' | Out-Null
        Test-Path (Join-Path $vault "90_Archive/$((Get-Date).Year)/fixture-project/README.md") | Should -BeTrue
    }
    It 'refuses repeated init on managed drift and preserves the user bytes and lock' {
        $vault=New-FixtureVault 'drift-init'
        $managed=Join-Path $vault '00_System/managed'
        $policy=Join-Path $managed 'policies/base-agent-rules.md'
        'fixture user customization' | Set-Content $policy
        $lock=Get-Content (Join-Path $managed 'kit-lock.json') -Raw
        {Invoke-KbInit $vault $script:kit} | Should -Throw
        Get-Content $policy -Raw | Should -Match 'fixture user customization'
        Get-Content (Join-Path $managed 'kit-lock.json') -Raw | Should -Be $lock
    }
    It 'refuses upgrade on drift or missing checksum' {
        $vault=New-FixtureVault 'drift-upgrade'
        $managed=Join-Path $vault '00_System/managed'
        $policy=Join-Path $managed 'policies/base-agent-rules.md'
        'fixture change' | Set-Content $policy
        {Invoke-KbUpgrade $vault $script:kit} | Should -Throw
        Get-Content $policy -Raw | Should -Match 'fixture change'
        $lock=Read-KbJson (Join-Path $managed 'kit-lock.json')
        $lock.managedFilesChecksum=$null
        Write-KbJson $lock (Join-Path $managed 'kit-lock.json')
        {Invoke-KbUpgrade $vault $script:kit} | Should -Throw
    }
    It 'does not initialize over unowned managed files' {
        $vault=Join-Path $TestDrive 'unowned'
        $managed=Join-Path $vault '00_System/managed'
        New-Item -ItemType Directory $managed -Force | Out-Null
        'fixture' | Set-Content (Join-Path $managed 'decision-log.md')
        {Invoke-KbInit $vault $script:kit} | Should -Throw
        Get-Content (Join-Path $managed 'decision-log.md') -Raw | Should -Match 'fixture'
    }
    It 'rejects backup into source, source subtree, repository or link' {
        $vault=New-FixtureVault 'backup-vault'
        $repo=Join-Path $TestDrive 'backup-repo'; New-Item -ItemType Directory (Join-Path $repo '.git') -Force | Out-Null
        $external=Join-Path $TestDrive 'backup-external'; New-Item -ItemType Directory $external | Out-Null
        $link=Join-Path $TestDrive 'backup-link'; New-FixtureLink $link $external
        foreach($target in @($vault,(Join-Path $vault 'nested'),$repo,$link)) {
            {Invoke-KbBackup $vault $target} | Should -Throw
        }
        Test-Path (Join-Path $vault 'nested') | Should -BeFalse
        @(Get-ChildItem $external).Count | Should -Be 0
    }
    It 'backs up to a fresh external destination preserving source' {
        $vault=New-FixtureVault 'backup-good'
        $dest=Join-Path $TestDrive 'backup-dest'
        $result=Invoke-KbBackup $vault $dest
        Test-Path (Join-Path $result.data.backupPath 'README.md') | Should -BeTrue
        Test-Path (Join-Path $vault 'README.md') | Should -BeTrue
    }
    It 'rejects managed junction before upgrade deletion' {
        $vault=New-FixtureVault 'linked-managed'
        $outside=Join-Path $TestDrive 'outside-policy'; New-Item -ItemType Directory $outside | Out-Null
        'keep' | Set-Content (Join-Path $outside 'keep.txt')
        New-FixtureLink (Join-Path $vault '00_System/managed/custom') $outside
        {Invoke-KbUpgrade $vault $script:kit} | Should -Throw
        Get-Content (Join-Path $outside 'keep.txt') -Raw | Should -Match 'keep'
    }
}

Describe 'Privacy scan completion is explicit' {
    It 'does not enumerate through a linked scan root' {
        $dir=Join-Path $TestDrive 'scan-outside'; New-Item -ItemType Directory $dir | Out-Null
        'fixture' | Set-Content (Join-Path $dir 'data.txt')
        $link=Join-Path $TestDrive 'scan-link'; New-FixtureLink $link $dir
        $scan=Invoke-KbPrivacyScan $link
        $scan.scannedCount | Should -Be 0
        $scan.complete | Should -BeFalse
        $scan.manualReview.Count | Should -Be 1
    }
    It 'reports every unknown extension as manual review' {
        $file=Join-Path $TestDrive 'fixture.unknown'
        [IO.File]::WriteAllBytes($file,[byte[]](1,2,3))
        $scan=Invoke-KbPrivacyScan $file
        $scan.complete | Should -BeFalse
        $scan.manualReview.Count | Should -Be 1
        $scan.scannedCount | Should -Be 0
    }
    It 'reports invalid UTF8 text as incomplete rather than silently scanning nothing' {
        $file=Join-Path $TestDrive 'invalid.txt'
        [IO.File]::WriteAllBytes($file,[byte[]](255,254,1))
        $scan=Invoke-KbPrivacyScan $file
        $scan.complete | Should -BeFalse
        $scan.readErrors.Count | Should -Be 1
    }
    It 'reports read errors without exposing the thrown exception body' {
        $file=Join-Path $TestDrive 'denied.txt'; 'fixture' | Set-Content $file
        Mock -ModuleName PrivacyScan Read-KbScanText {throw 'fixture-sensitive-error-body'}
        $scan=Invoke-KbPrivacyScan $file
        $scan.complete | Should -BeFalse
        $scan.readErrors.Count | Should -Be 1
        ($scan.readErrors -join '') | Should -Not -Match 'fixture-sensitive-error-body'
    }
    It 'reports a missing path as incomplete' {
        (Invoke-KbPrivacyScan (Join-Path $TestDrive 'missing')).complete | Should -BeFalse
    }
    It 'doctor cannot call an unknown file fully reviewed; quick marks scan not-run' {
        $vault=New-FixtureVault 'doctor-incomplete'
        [IO.File]::WriteAllBytes((Join-Path $vault 'fixture.bin'),[byte[]](1,2,3))
        $result=Invoke-KbDoctor $vault $script:kit
        $result.state | Should -Be 'DEGRADED'
        $result.data.privacyComplete | Should -BeFalse
        $quick=Invoke-KbDoctor $vault $script:kit -Quick
        $quick.data.privacyScan | Should -Be 'not-run'
        $quick.data.privacyComplete | Should -BeFalse
    }
}
