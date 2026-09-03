#Requires -Version 5.1
<#
.SYNOPSIS
    Proves that genekit resolves anonymously (no credentials) from its pinned tags.

.DESCRIPTION
    On a developer workstation every plausible "no credentials" setup still succeeds by accident:
    Git for Windows installs `credential.helper=manager` in the SYSTEM gitconfig
    (C:/Program Files/Git/etc/gitconfig), so GIT_CONFIG_GLOBAL alone does NOT disable it and a naive
    "anonymous" test passes for the wrong reason -- using a cached token rather than proving public
    resolution. GIT_CONFIG_NOSYSTEM=1 is the load-bearing variable.

    This script therefore runs three controls before any real leg and refuses to interpret results
    unless they all come out right:

        C1  UNSCRUBBED  git ls-remote <private control repo>   MUST succeed
                        (proves credentials exist, the network is up, and the control repo is still
                         private-but-reachable; without C1 the whole design fails open -- a network
                         outage would make the scrub look effective)
        C2  SCRUBBED    git ls-remote <private control repo>   MUST fail with an auth error
                        (proves the credential scrub is real)
        C3  SCRUBBED    git ls-remote --tags <genekit>         MUST succeed at the recorded SHAs

    Then, for each tag x each of {bare, rich}, it builds a synthetic consumer that mirrors the real
    consumer pin shape (git+https + subdirectory = "python" + tag), runs a scrubbed `uv sync --refresh`
    against a fresh UV_CACHE_DIR, and asserts the resolved commit SHA, the installed version, and a
    version-discriminating symbol (`rotate_bytes` is a parameter of configure_logging at py-v0.2.0 and
    absent at py-v0.1.0), so a warm cache or a mis-resolved tag cannot produce a green run.

.PARAMETER KeepWorkDir
    Keep the per-run work directory instead of deleting it (deletion otherwise happens in a finally).

.OUTPUTS
    A summary table, plus an exit code:
        0  all controls and legs passed
        1  a leg failed (controls were sound -- the finding is real)
        2  a control, precondition, or the harness itself failed (results invalid; do NOT interpret legs)

.NOTES
    Target: Windows PowerShell 5.1. No `&&`/`||`, no ternary, no null-coalescing; $LASTEXITCODE is
    checked explicitly after every native call; stderr from native calls is captured by redirecting to
    a file, never by piping `2>&1` (which wraps stderr in NativeCommandError and falsifies `$?`).

    Deliberately NOT wired into CI: a GitHub runner has no user credentials to scrub, so control C2 is
    vacuous there and a green run would prove nothing.

.EXAMPLE
    .\verify-anonymous-install.ps1

.EXAMPLE
    .\verify-anonymous-install.ps1 -Tags py-v0.2.0 -KeepWorkDir
#>
[CmdletBinding()]
param(
    [string[]] $Tags = @('py-v0.1.0', 'py-v0.2.0'),
    [string]   $Repo = 'https://github.com/TheGeneCode/genekit',
    [string]   $PrivateControlRepo = 'https://github.com/TheGeneCode/remove-the-bloat',
    [string]   $PythonPath = 'C:/Python314/python.exe',
    [string]   $WorkRoot = (Join-Path $env:TEMP 'genekit-anon-verify'),
    [switch]   $KeepWorkDir
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------------------------------
# Expected-state tables -- the anti-false-pass anchors.
# ---------------------------------------------------------------------------------------------------

$ExpectedCommit = @{
    'py-v0.1.0' = 'c82246c4b5f327338751a47e7909c5b4316794cf'
    'py-v0.2.0' = '660fbd04c59651185495fc6f7af57e208f833aa3'
}
$ExpectedVersion = @{ 'py-v0.1.0' = '0.1.0'; 'py-v0.2.0' = '0.2.0' }
# rotate_bytes was added in py-v0.2.0; its ABSENCE at py-v0.1.0 proves the older tag really resolved.
$ExpectsRotateBytes = @{ 'py-v0.1.0' = $false; 'py-v0.2.0' = $true }

# stderr of a credential-less fetch against a repo the caller cannot see.
$AuthFailurePattern = 'could not read Username|Authentication failed|terminal prompts disabled|Repository not found'

$Variants = @('bare', 'rich')

# ---------------------------------------------------------------------------------------------------
# Shared mutable state
# ---------------------------------------------------------------------------------------------------

$script:Results = New-Object System.Collections.ArrayList
$script:RunDir = $null
$script:ScrubRemoveNames = @()
$script:ScrubSetMap = @{}

# ---------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------

function Write-Utf8File {
    # UTF-8 without a BOM: git's config parser and TOML readers are both happier without one,
    # and a BOM is not part of what "-Encoding utf8" is asking for here.
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string] $Content
    )
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][string] $Check,
        [Parameter(Mandatory = $true)][string] $Expected,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string] $Actual,
        [Parameter(Mandatory = $true)][ValidateSet('PASS', 'FAIL', 'INFO')][string] $Status,
        [string] $Detail = ''
    )
    $row = [pscustomobject]@{
        Check    = $Check
        Expected = $Expected
        Actual   = $Actual
        Status   = $Status
        Detail   = $Detail
    }
    [void] $script:Results.Add($row)
    return $row
}

function Format-Cell {
    param([AllowEmptyString()][string] $Text, [int] $Width)
    if ($null -eq $Text) { $Text = '' }
    $Text = ($Text -replace '\s+', ' ').Trim()
    if ($Text.Length -gt $Width) { $Text = $Text.Substring(0, $Width - 3) + '...' }
    return $Text.PadRight($Width)
}

function Get-CleanStderr {
    # Windows PowerShell 5.1 surfaces a native command's stderr as one ErrorRecord per line, and a `2>`
    # file redirect writes the *rendered* record -- "<exe> : <text>", then "At line:N char:M", the
    # offending source line, a squiggle line, CategoryInfo and FullyQualifiedErrorId. That decoration
    # buries a real `uv sync` failure. Strip it for display; the raw text is kept for pattern matching.
    param([AllowEmptyString()][string] $Raw)
    if ([string]::IsNullOrEmpty($Raw)) { return '' }
    $kept = New-Object System.Collections.ArrayList
    foreach ($line in ($Raw -split "`r?`n")) {
        if ($line -match '^At line:\d+ char:\d+') { continue }
        if ($line -match '^\s*\+\s') { continue }
        $line = $line -replace '^\S+\.exe\s:\s', ''
        if ($line.Trim().Length -eq 0) { continue }
        [void] $kept.Add($line)
    }
    return ($kept -join "`r`n")
}

function Get-Snippet {
    param([AllowEmptyString()][string] $Text, [int] $Max = 600)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $t = $Text.Trim()
    if ($t.Length -gt $Max) { $t = $t.Substring(0, $Max) + ' ...[truncated]' }
    return $t
}

# ---------------------------------------------------------------------------------------------------
# Native invocation -- stderr goes to a file, never through `2>&1`.
# ---------------------------------------------------------------------------------------------------

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]   $FilePath,
        [Parameter(Mandatory = $true)][string[]] $ArgumentList,
        [string] $WorkingDirectory
    )

    $errDir = $script:RunDir
    if ([string]::IsNullOrEmpty($errDir)) { $errDir = $env:TEMP }
    $errFile = Join-Path $errDir ('stderr-' + [guid]::NewGuid().ToString('N') + '.txt')

    $prevEap = $ErrorActionPreference
    $prevLocation = $null
    $stdoutLines = $null
    $code = $null

    # A native command's stderr surfaces as ErrorRecords; with EAP=Stop that would abort the harness on
    # any tool that merely chatters to stderr. Redirect the stream to a file under EAP=Continue instead.
    $ErrorActionPreference = 'Continue'
    try {
        if (-not [string]::IsNullOrEmpty($WorkingDirectory)) {
            $prevLocation = (Get-Location).Path
            Set-Location -LiteralPath $WorkingDirectory
        }
        $global:LASTEXITCODE = 0
        $stdoutLines = & $FilePath @ArgumentList 2> $errFile
        $code = $LASTEXITCODE
    }
    finally {
        if ($null -ne $prevLocation) { Set-Location -LiteralPath $prevLocation }
        $ErrorActionPreference = $prevEap
    }

    $stderrText = ''
    if (Test-Path -LiteralPath $errFile) {
        $raw = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
        if ($null -ne $raw) { $stderrText = $raw }
        Remove-Item -LiteralPath $errFile -Force -ErrorAction SilentlyContinue
    }

    $stdoutText = ''
    if ($null -ne $stdoutLines) { $stdoutText = ($stdoutLines | Out-String) }

    return [pscustomobject]@{
        ExitCode  = $code
        StdOut    = $stdoutText
        # Cleaned for display; StdErrRaw is what pattern matching runs against, so no filter of ours
        # can hide a substring a control depends on.
        StdErr    = (Get-CleanStderr $stderrText)
        StdErrRaw = $stderrText
        Command   = ($FilePath + ' ' + ($ArgumentList -join ' '))
    }
}

# ---------------------------------------------------------------------------------------------------
# Environment scrub
# ---------------------------------------------------------------------------------------------------

function Initialize-ScrubPlan {
    param([Parameter(Mandatory = $true)][string] $RunDir)

    $homeDir = Join-Path $RunDir 'home'
    $xdgDir = Join-Path $homeDir '.config'
    $gitConfigPath = Join-Path $homeDir '.gitconfig'
    $uvCacheDir = Join-Path $RunDir 'uvcache'
    $uvConfigPath = Join-Path $RunDir 'uv.toml'

    New-Item -ItemType Directory -Path $homeDir -Force | Out-Null
    New-Item -ItemType Directory -Path $xdgDir -Force | Out-Null
    New-Item -ItemType Directory -Path $uvCacheDir -Force | Out-Null

    # An EMPTY value resets any inherited helper list. It has to live in a config FILE, not an env var:
    # assigning '' to an env var in PowerShell deletes the variable, so a GIT_CONFIG_COUNT /
    # GIT_CONFIG_VALUE_0 trick would leave git erroring on a missing config value. This file travels
    # through uv, because uv shells out to the git CLI.
    Write-Utf8File -Path $gitConfigPath -Content "[credential]`r`n`thelper =`r`n"

    # Empty on purpose: detaches %APPDATA%\uv\uv.toml.
    Write-Utf8File -Path $uvConfigPath -Content ''

    $script:ScrubRemoveNames = @(
        'GH_TOKEN'
        'GITHUB_TOKEN'
        'GH_ENTERPRISE_TOKEN'
        'GIT_ASKPASS'
        'SSH_ASKPASS'
        'GIT_USERNAME'
        'GIT_PASSWORD'
        'GIT_CONFIG_COUNT'
        'GIT_CONFIG_PARAMETERS'
        # VIRTUAL_ENV is not optional hygiene: an inherited value makes uv resolve UV_PYTHON to a
        # nonexistent interpreter and abort before any network call, so every leg fails for an
        # unrelated reason.
        'VIRTUAL_ENV'
        'PYTHONHOME'
        'PYTHONPATH'
    )

    $script:ScrubSetMap = @{
        # LOAD-BEARING: credential.helper=manager lives in C:/Program Files/Git/etc/gitconfig, i.e. the
        # SYSTEM config -- GIT_CONFIG_GLOBAL alone does not disable it. Do not "simplify" this away.
        'GIT_CONFIG_NOSYSTEM' = '1'
        # Detaches ~/.gitconfig and any insteadOf rewrite.
        'GIT_CONFIG_GLOBAL'   = $gitConfigPath
        # Hide ~/.git-credentials, _netrc, ~/.config. GCM reads USERPROFILE.
        'HOME'                = $homeDir
        'USERPROFILE'         = $homeDir
        'XDG_CONFIG_HOME'     = $xdgDir
        # Turn "would prompt" into a deterministic hard failure instead of a hang.
        'GIT_TERMINAL_PROMPT' = '0'
        # Belt-and-braces if a helper is somehow still reached.
        'GCM_INTERACTIVE'     = 'never'
        'GCM_CREDENTIAL_STORE' = 'none'
        # A warm cache would resolve with no network call at all.
        'UV_CACHE_DIR'        = $uvCacheDir
        'UV_CONFIG_FILE'      = $uvConfigPath
        'UV_PYTHON'           = $PythonPath
        # A silent managed-Python download would mask a bad -PythonPath.
        'UV_PYTHON_DOWNLOADS' = 'never'
    }
}

function Invoke-Scrubbed {
    param([Parameter(Mandatory = $true)][scriptblock] $Body)

    $names = New-Object System.Collections.ArrayList
    foreach ($n in $script:ScrubRemoveNames) { [void] $names.Add($n) }
    foreach ($n in $script:ScrubSetMap.Keys) { [void] $names.Add($n) }

    # Snapshot everything we are about to touch. Restoration is unconditional: an interrupted run must
    # not leave the interactive session credential-less.
    $snapshot = @{}
    foreach ($n in $names) {
        if (-not $snapshot.ContainsKey($n)) {
            $snapshot[$n] = [Environment]::GetEnvironmentVariable($n, 'Process')
        }
    }

    try {
        foreach ($n in $script:ScrubRemoveNames) {
            Remove-Item -LiteralPath ('Env:\' + $n) -ErrorAction SilentlyContinue
        }
        foreach ($n in $script:ScrubSetMap.Keys) {
            [Environment]::SetEnvironmentVariable($n, $script:ScrubSetMap[$n], 'Process')
        }
        & $Body
    }
    finally {
        foreach ($n in @($snapshot.Keys)) {
            $v = $snapshot[$n]
            if ($null -eq $v) {
                Remove-Item -LiteralPath ('Env:\' + $n) -ErrorAction SilentlyContinue
            }
            else {
                [Environment]::SetEnvironmentVariable($n, $v, 'Process')
            }
        }
    }
}

# ---------------------------------------------------------------------------------------------------
# Preconditions -- a broken harness must not masquerade as a real finding (exit 2, not 1).
# ---------------------------------------------------------------------------------------------------

function Test-Preconditions {
    $ok = $true

    foreach ($exe in @('git', 'uv')) {
        $cmd = Get-Command $exe -ErrorAction SilentlyContinue
        if ($null -eq $cmd) {
            Add-Result -Check ("PRECONDITION " + $exe + " on PATH") -Expected 'found' -Actual 'not found' -Status 'FAIL' | Out-Null
            $ok = $false
        }
        else {
            Add-Result -Check ("PRECONDITION " + $exe + " on PATH") -Expected 'found' -Actual $cmd.Source -Status 'PASS' | Out-Null
        }
    }

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        # UV_PYTHON_DOWNLOADS=never means a bad interpreter path fails every leg for a reason that has
        # nothing to do with anonymous resolution.
        Add-Result -Check 'PRECONDITION interpreter exists' -Expected $PythonPath -Actual 'missing' -Status 'FAIL' | Out-Null
        $ok = $false
    }
    else {
        Add-Result -Check 'PRECONDITION interpreter exists' -Expected $PythonPath -Actual 'present' -Status 'PASS' | Out-Null
    }

    foreach ($tag in $Tags) {
        $known = $ExpectedCommit.ContainsKey($tag) -and $ExpectedVersion.ContainsKey($tag) -and $ExpectsRotateBytes.ContainsKey($tag)
        if (-not $known) {
            Add-Result -Check ("PRECONDITION expected-state for " + $tag) -Expected 'commit/version/rotate_bytes all recorded' -Actual 'tag absent from the expected-state tables' -Status 'FAIL' | Out-Null
            $ok = $false
        }
        else {
            Add-Result -Check ("PRECONDITION expected-state for " + $tag) -Expected 'commit/version/rotate_bytes all recorded' -Actual 'recorded' -Status 'PASS' | Out-Null
        }
    }

    return $ok
}

# ---------------------------------------------------------------------------------------------------
# Controls C1 / C2 / C3
# ---------------------------------------------------------------------------------------------------

function Invoke-Controls {
    # --- C1: UNSCRUBBED probe of a known-private repo. MUST succeed. -------------------------------
    # Without this, a network outage or a revoked token would make the scrub look effective and the
    # whole design would fail open.
    Write-Host 'C1  unscrubbed  git ls-remote (private control repo) ...'
    $c1 = Invoke-Native -FilePath 'git' -ArgumentList @('ls-remote', $PrivateControlRepo)
    if ($c1.ExitCode -ne 0) {
        Add-Result -Check 'C1 creds-present control' -Expected 'exit 0' -Actual ('exit ' + $c1.ExitCode) -Status 'FAIL' `
            -Detail ("Credentials are absent, the network is down, or the control repo is no longer private-but-reachable.`n" + (Get-Snippet $c1.StdErr)) | Out-Null
        Write-Host 'CONTROL C1 FAILED - results would be meaningless' -ForegroundColor Red
        return $false
    }
    Add-Result -Check 'C1 creds-present control' -Expected 'exit 0' -Actual 'exit 0' -Status 'PASS' | Out-Null

    # --- C2: SCRUBBED probe of that same private repo. MUST fail with an auth error. ---------------
    # This is the negative control that makes every result below meaningful.
    Write-Host 'C2  scrubbed    git ls-remote (private control repo) ...'
    $c2 = Invoke-Scrubbed { Invoke-Native -FilePath 'git' -ArgumentList @('ls-remote', $PrivateControlRepo) }
    if ($c2.ExitCode -eq 0) {
        Add-Result -Check 'C2 scrub-is-real control' -Expected 'non-zero exit + auth-failure stderr' -Actual 'exit 0 (succeeded)' -Status 'FAIL' `
            -Detail 'The scrubbed environment still reaches a private repo, so credentials survived the scrub.' | Out-Null
        Write-Host 'CONTROL C2 FAILED - credential scrub is leaking; every anonymous result below would be a false pass' -ForegroundColor Red
        return $false
    }
    $c2Text = $c2.StdErrRaw + "`n" + $c2.StdOut
    if ($c2Text -notmatch $AuthFailurePattern) {
        Add-Result -Check 'C2 scrub-is-real control' -Expected 'non-zero exit + auth-failure stderr' -Actual ('exit ' + $c2.ExitCode + ', stderr did not match the auth-failure pattern') -Status 'FAIL' `
            -Detail ("Failed for some other reason (DNS, proxy, TLS?), so the scrub is unproven.`n" + (Get-Snippet $c2.StdErr)) | Out-Null
        Write-Host 'CONTROL C2 FAILED - credential scrub is leaking; every anonymous result below would be a false pass' -ForegroundColor Red
        return $false
    }
    Add-Result -Check 'C2 scrub-is-real control' -Expected 'non-zero exit + auth-failure stderr' -Actual ('exit ' + $c2.ExitCode + ', auth-failure stderr matched') -Status 'PASS' | Out-Null

    # --- C3: SCRUBBED tag listing for genekit. MUST succeed at the recorded SHAs. ------------------
    Write-Host 'C3  scrubbed    git ls-remote --tags (genekit) ...'
    $c3 = Invoke-Scrubbed { Invoke-Native -FilePath 'git' -ArgumentList @('ls-remote', '--tags', $Repo) }
    if ($c3.ExitCode -ne 0) {
        Add-Result -Check 'C3 genekit is public' -Expected 'exit 0' -Actual ('exit ' + $c3.ExitCode) -Status 'FAIL' `
            -Detail (Get-Snippet $c3.StdErr) | Out-Null
        Write-Host 'CONTROL C3 FAILED - results would be meaningless' -ForegroundColor Red
        return $false
    }
    Add-Result -Check 'C3 genekit is public' -Expected 'exit 0' -Actual 'exit 0' -Status 'PASS' | Out-Null

    $c3Ok = $true
    foreach ($tag in $Tags) {
        $want = $ExpectedCommit[$tag]
        # The peeled ref (`^{}`) is the commit the annotated tag points at.
        $pattern = '(?m)^([0-9a-fA-F]{40})\s+refs/tags/' + [regex]::Escape($tag) + '\^\{\}\s*$'
        $got = '<no peeled ^{} line>'
        $m = [regex]::Match($c3.StdOut, $pattern)
        if ($m.Success) { $got = $m.Groups[1].Value }
        if ($got -eq $want) {
            Add-Result -Check ('C3 tag target ' + $tag) -Expected $want -Actual $got -Status 'PASS' | Out-Null
        }
        else {
            Add-Result -Check ('C3 tag target ' + $tag) -Expected $want -Actual $got -Status 'FAIL' `
                -Detail 'A tag moved, or the tag is not annotated. Everything downstream of the tag contract is invalid.' | Out-Null
            $c3Ok = $false
        }
    }
    if (-not $c3Ok) {
        Write-Host 'CONTROL C3 FAILED - a tag target moved; results would be meaningless' -ForegroundColor Red
        return $false
    }

    return $true
}

# ---------------------------------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------------------------------

function Get-LockedGenekitSha {
    param([Parameter(Mandatory = $true)][string] $LockPath)

    if (-not (Test-Path -LiteralPath $LockPath)) { return $null }
    $lockText = Get-Content -LiteralPath $LockPath -Raw
    if ([string]::IsNullOrEmpty($lockText)) { return $null }

    foreach ($block in ($lockText -split '(?m)^\[\[package\]\]\s*$')) {
        if ($block -match '(?m)^\s*name\s*=\s*"genekit"\s*$') {
            if ($block -match 'source\s*=\s*\{[^}]*#([0-9a-fA-F]{40})') { return $Matches[1] }
            return $null
        }
    }
    return $null
}

function New-LegPyproject {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Tag,
        [Parameter(Mandatory = $true)][string] $Variant
    )
    $dep = 'genekit'
    if ($Variant -eq 'rich') { $dep = 'genekit[rich]' }

    # Mirrors the real consumer pin shape: git+https + subdirectory = "python" + tag.
    $toml = @"
[project]
name = "genekit-anon-check"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = ["$dep"]

[tool.uv.sources]
genekit = { git = "$Repo", subdirectory = "python", tag = "$Tag" }
"@
    Write-Utf8File -Path $Path -Content ($toml + "`r`n")
}

function Invoke-Leg {
    param(
        [Parameter(Mandatory = $true)][string] $Tag,
        [Parameter(Mandatory = $true)][string] $Variant
    )

    $legName = 'leg ' + $Tag + ' ' + $Variant
    $legDir = Join-Path $script:RunDir ('leg-' + $Tag + '-' + $Variant)
    $ok = $true

    Write-Host ('LEG ' + $Tag + ' / ' + $Variant + ' ...')

    if (Test-Path -LiteralPath $legDir) { Remove-Item -LiteralPath $legDir -Recurse -Force }
    New-Item -ItemType Directory -Path $legDir -Force | Out-Null
    New-LegPyproject -Path (Join-Path $legDir 'pyproject.toml') -Tag $Tag -Variant $Variant

    # --- 1. scrubbed `uv sync --refresh` against a fresh UV_CACHE_DIR ------------------------------
    $sync = Invoke-Scrubbed { Invoke-Native -FilePath 'uv' -ArgumentList @('sync', '--refresh') -WorkingDirectory $legDir }
    if ($sync.ExitCode -ne 0) {
        Add-Result -Check ($legName + ' / uv sync') -Expected 'exit 0' -Actual ('exit ' + $sync.ExitCode) -Status 'FAIL' `
            -Detail (Get-Snippet $sync.StdErr) | Out-Null
        return $false
    }
    Add-Result -Check ($legName + ' / uv sync') -Expected 'exit 0' -Actual 'exit 0' -Status 'PASS' | Out-Null

    # --- 2. the resolved commit SHA in the generated lock ------------------------------------------
    $wantSha = $ExpectedCommit[$Tag]
    $gotSha = Get-LockedGenekitSha -LockPath (Join-Path $legDir 'uv.lock')
    if ($null -eq $gotSha) { $gotSha = '<no genekit git source in uv.lock>' }
    if ($gotSha -eq $wantSha) {
        Add-Result -Check ($legName + ' / lock sha') -Expected $wantSha -Actual $gotSha -Status 'PASS' | Out-Null
    }
    else {
        Add-Result -Check ($legName + ' / lock sha') -Expected $wantSha -Actual $gotSha -Status 'FAIL' | Out-Null
        $ok = $false
    }

    # --- 3. in-venv probe: installed version + version-discriminating symbol -----------------------
    # Single-quoted inside the Python source on purpose: PowerShell 5.1 mangles embedded double quotes
    # when it hands an argument to a native executable.
    $probe = "import importlib.metadata as md, inspect; from genekit.logging import configure_logging; print('VERSION=' + md.version('genekit')); print('ROTATE=' + str('rotate_bytes' in inspect.signature(configure_logging).parameters))"
    if ($Variant -eq 'rich') { $probe = $probe + "; print('RICH=' + md.version('rich'))" }

    $run = Invoke-Scrubbed { Invoke-Native -FilePath 'uv' -ArgumentList @('run', '--no-sync', 'python', '-c', $probe) -WorkingDirectory $legDir }
    if ($run.ExitCode -ne 0) {
        Add-Result -Check ($legName + ' / probe') -Expected 'exit 0' -Actual ('exit ' + $run.ExitCode) -Status 'FAIL' `
            -Detail (Get-Snippet $run.StdErr) | Out-Null
        return $false
    }
    Add-Result -Check ($legName + ' / probe') -Expected 'exit 0' -Actual 'exit 0' -Status 'PASS' | Out-Null

    $gotVersion = '<not printed>'
    if ($run.StdOut -match '(?m)^VERSION=(.+?)\s*$') { $gotVersion = $Matches[1] }
    $wantVersion = $ExpectedVersion[$Tag]
    if ($gotVersion -eq $wantVersion) {
        Add-Result -Check ($legName + ' / VERSION') -Expected $wantVersion -Actual $gotVersion -Status 'PASS' | Out-Null
    }
    else {
        Add-Result -Check ($legName + ' / VERSION') -Expected $wantVersion -Actual $gotVersion -Status 'FAIL' | Out-Null
        $ok = $false
    }

    $gotRotate = '<not printed>'
    if ($run.StdOut -match '(?m)^ROTATE=(.+?)\s*$') { $gotRotate = $Matches[1] }
    $wantRotate = 'False'
    if ($ExpectsRotateBytes[$Tag]) { $wantRotate = 'True' }
    if ($gotRotate -eq $wantRotate) {
        Add-Result -Check ($legName + ' / ROTATE') -Expected $wantRotate -Actual $gotRotate -Status 'PASS' | Out-Null
    }
    else {
        Add-Result -Check ($legName + ' / ROTATE') -Expected $wantRotate -Actual $gotRotate -Status 'FAIL' `
            -Detail 'The version-discriminating symbol disagrees with the tag: the wrong tree resolved, or a cache was reused.' | Out-Null
        $ok = $false
    }

    if ($Variant -eq 'rich') {
        $gotRich = '<not printed>'
        if ($run.StdOut -match '(?m)^RICH=(.+?)\s*$') { $gotRich = $Matches[1] }
        if ($gotRich -eq '<not printed>') {
            Add-Result -Check ($legName + ' / RICH') -Expected 'a RICH= line' -Actual $gotRich -Status 'FAIL' `
                -Detail 'The [rich] extra did not install.' | Out-Null
            $ok = $false
        }
        else {
            Add-Result -Check ($legName + ' / RICH') -Expected 'a RICH= line' -Actual ('rich ' + $gotRich) -Status 'PASS' | Out-Null
        }
    }

    # --- 4. license presence: INFORMATIONAL, never a failure ---------------------------------------
    # Neither current tag ships the MIT LICENSE (it landed after py-v0.2.0), so anonymous consumers of
    # the current pins receive all-rights-reserved code. Reported here so the gap stays visible; the
    # fix is a new tag, not an edit, and is out of scope for this harness.
    $licenseState = '<dist-info not found>'
    $sitePackages = Join-Path $legDir '.venv\Lib\site-packages'
    if (Test-Path -LiteralPath $sitePackages) {
        $distInfo = Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'genekit-*.dist-info' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $distInfo) {
            if (Test-Path -LiteralPath (Join-Path $distInfo.FullName 'licenses\LICENSE')) {
                $licenseState = 'LICENSE=present'
            }
            else {
                $licenseState = 'LICENSE=absent (expected for this tag)'
            }
        }
    }
    Write-Host ('    ' + $licenseState)
    Add-Result -Check ($legName + ' / license (info)') -Expected 'informational only' -Actual $licenseState -Status 'INFO' | Out-Null

    return $ok
}

# ---------------------------------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------------------------------

function Write-Summary {
    $checkW = 6
    foreach ($r in $script:Results) { if ($r.Check.Length -gt $checkW) { $checkW = $r.Check.Length } }
    if ($checkW -gt 44) { $checkW = 44 }
    $expW = 44
    $actW = 44

    Write-Host ''
    Write-Host '================================ SUMMARY ================================'
    Write-Host ('STAT  ' + (Format-Cell 'CHECK' $checkW) + '  ' + (Format-Cell 'EXPECTED' $expW) + '  ' + (Format-Cell 'ACTUAL' $actW))
    Write-Host ('----  ' + ('-' * $checkW) + '  ' + ('-' * $expW) + '  ' + ('-' * $actW))

    foreach ($r in $script:Results) {
        $line = $r.Status.PadRight(4) + '  ' + (Format-Cell $r.Check $checkW) + '  ' + (Format-Cell $r.Expected $expW) + '  ' + (Format-Cell $r.Actual $actW)
        if ($r.Status -eq 'FAIL') { Write-Host $line -ForegroundColor Red }
        elseif ($r.Status -eq 'INFO') { Write-Host $line -ForegroundColor DarkGray }
        else { Write-Host $line -ForegroundColor Green }
    }

    $failed = @($script:Results | Where-Object { $_.Status -eq 'FAIL' -and -not [string]::IsNullOrEmpty($_.Detail) })
    if ($failed.Count -gt 0) {
        Write-Host ''
        Write-Host '--------------------------------- DETAIL --------------------------------'
        foreach ($r in $failed) {
            Write-Host ('* ' + $r.Check) -ForegroundColor Red
            Write-Host $r.Detail
            Write-Host ''
        }
    }
}

function Remove-RunDirectory {
    param([Parameter(Mandatory = $true)][string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    }
    catch {
        # git object/pack files land read-only; clear the attribute and try once more.
        try {
            Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue |
                ForEach-Object { try { $_.Attributes = 'Normal' } catch { } }
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        }
        catch {
            Write-Warning ('Could not delete the work directory: ' + $Path)
        }
    }
}

# ---------------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------------

$exitCode = 0

try {
    $runId = 'run-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $PID
    $script:RunDir = Join-Path $WorkRoot $runId
    New-Item -ItemType Directory -Path $script:RunDir -Force | Out-Null

    Write-Host 'genekit anonymous-resolution harness'
    Write-Host ('  repo          : ' + $Repo)
    Write-Host ('  control repo  : ' + $PrivateControlRepo)
    Write-Host ('  tags          : ' + ($Tags -join ', '))
    Write-Host ('  interpreter   : ' + $PythonPath)
    Write-Host ('  work dir      : ' + $script:RunDir)
    Write-Host ''

    Initialize-ScrubPlan -RunDir $script:RunDir

    if (-not (Test-Preconditions)) {
        Write-Host 'PRECONDITIONS FAILED - the harness cannot produce an interpretable result' -ForegroundColor Red
        $exitCode = 2
    }
    elseif (-not (Invoke-Controls)) {
        # A control failure means the run said nothing at all. No legs run; do not interpret anything.
        $exitCode = 2
    }
    else {
        $anyLegFailed = $false
        foreach ($tag in $Tags) {
            foreach ($variant in $Variants) {
                $legOk = Invoke-Leg -Tag $tag -Variant $variant
                if (-not $legOk) { $anyLegFailed = $true }
            }
        }
        if ($anyLegFailed) { $exitCode = 1 }
    }
}
catch {
    # A harness crash is a control-class failure: the results are not interpretable.
    Write-Host ''
    Write-Host ('HARNESS ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    if ($null -ne $_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
    Add-Result -Check 'harness' -Expected 'no unhandled error' -Actual $_.Exception.Message -Status 'FAIL' | Out-Null
    $exitCode = 2
}
finally {
    Write-Summary

    Write-Host ''
    if ($exitCode -eq 0) {
        Write-Host 'RESULT: exit 0 - all controls and legs passed; anonymous resolution is proven.' -ForegroundColor Green
    }
    elseif ($exitCode -eq 1) {
        Write-Host 'RESULT: exit 1 - a leg FAILED. Controls were sound, so the finding is real.' -ForegroundColor Red
    }
    else {
        Write-Host 'RESULT: exit 2 - a control/precondition FAILED. The run said nothing; do NOT interpret the legs.' -ForegroundColor Red
    }

    if ($null -ne $script:RunDir) {
        if ($KeepWorkDir) {
            Write-Host ('Work directory kept: ' + $script:RunDir)
        }
        else {
            Remove-RunDirectory -Path $script:RunDir
        }
    }
}

exit $exitCode
