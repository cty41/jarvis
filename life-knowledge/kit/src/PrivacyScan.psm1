Set-StrictMode -Version Latest

function Protect-KbPreview {
    param([string]$Text)
    if(-not $Text){return ''}
    if($Text.Length -le 4){return '***'}
    return $Text.Substring(0,2) + '***' + $Text.Substring($Text.Length-2)
}

function Invoke-KbPrivacyScan {
    param([Parameter(Mandatory)][string]$Path)
    $patterns = @(
        @{category='identity-number'; regex='(?<!\d)\d{17}[0-9Xx](?!\d)'},
        @{category='phone'; regex='(?<!\d)1[3-9]\d{9}(?!\d)'},
        @{category='private-key'; regex='-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'},
        @{category='token'; regex='(?i)(?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*["'']?[^\s"'']{8,}'},
        @{category='brokerage-account'; regex='(?i)(?:证券|券商|资金账号|brokerage account)\s*[:：=]\s*\w{6,}'}
    )
    $textExt = @('.md','.txt','.csv','.json','.html','.htm','.xml','.ini','.yaml','.yml','.ps1','.psm1','.py','.lua','.log')
    $findings = [Collections.Generic.List[object]]::new()
    $manual = [Collections.Generic.List[string]]::new()
    $readErrors = [Collections.Generic.List[string]]::new()
    $scanned = 0
    $enumErrors = @()
    if (-not (Test-Path -LiteralPath $Path)) {
        $readErrors.Add('Scan path unavailable')
        $files = @()
    } elseif ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $manual.Add([IO.Path]::GetFullPath($Path))
        $files=@()
    } elseif (Test-Path -LiteralPath $Path -PathType Leaf) {
        $files = @(Get-Item -LiteralPath $Path -Force)
    } else {
        # Do not follow reparse directories. Report every link/unknown format.
        $files = @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable enumErrors)
    }
    foreach($err in $enumErrors){$readErrors.Add('Directory enumeration incomplete')}
    foreach($file in $files){
        if($file.Attributes -band [IO.FileAttributes]::ReparsePoint){$manual.Add($file.FullName);continue}
        if($file.PSIsContainer){continue}
        if($textExt -notcontains $file.Extension.ToLowerInvariant()){$manual.Add($file.FullName);continue}
        try {
            $text = Read-KbScanText $file.FullName
            if($text.Contains([char]0)){throw 'Binary content in text file'}
            $lines = @($text -split '\r?\n')
        } catch {
            $readErrors.Add("Unreadable or non-text file: $($file.FullName)")
            continue
        }
        $scanned++
        for($i=0;$i -lt $lines.Count;$i++){
            foreach($p in $patterns){
                $m=[regex]::Match([string]$lines[$i],$p.regex)
                if($m.Success){$findings.Add([pscustomobject]@{file=$file.FullName;line=$i+1;category=$p.category;preview=(Protect-KbPreview $m.Value)})}
            }
        }
    }
    [pscustomobject]@{findings=$findings.ToArray();manualReview=$manual.ToArray();readErrors=$readErrors.ToArray();scannedCount=$scanned;complete=($manual.Count -eq 0 -and $readErrors.Count -eq 0);scannedAt=(Get-Date).ToString('o')}

}

function Read-KbScanText {
    param([string]$Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    return [Text.UTF8Encoding]::new($false,$true).GetString($bytes)
}

Export-ModuleMember -Function Invoke-KbPrivacyScan,Protect-KbPreview
