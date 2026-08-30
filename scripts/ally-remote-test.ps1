[CmdletBinding()]
param(
    [ValidateSet("Preflight", "Snapshot", "Capture", "Deploy")]
    [string]$Action = "Preflight",

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9._:-]+$")]
    [string]$HostName,

    [ValidatePattern("^[A-Za-z_][A-Za-z0-9_-]*$")]
    [string]$UserName = "deck",

    [ValidateRange(1, 65535)]
    [int]$Port = 22,

    [string]$IdentityFile = "",

    [ValidatePattern("^/[A-Za-z0-9._/-]+$")]
    [string]$RemotePluginDir = "",

    [ValidatePattern("^/[A-Za-z0-9._/-]+$")]
    [string]$RemoteStateDir = "",

    [ValidateRange(1, 120)]
    [int]$DurationMinutes = 15,

    [string]$OutputRoot = "",

    [switch]$IncludeSensitive,
    [switch]$InteractiveSudo,
    [switch]$ConfirmDeploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($RemoteStateDir)) {
    $RemoteStateDir = "/home/$UserName/homebrew/plugins/eGPUBridge"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $RepositoryRoot "test-results"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$SshHost = if ($HostName.Contains(":")) { "[$HostName]" } else { $HostName }
$Target = "$UserName@$SshHost"

foreach ($tool in @("ssh", "scp")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool was not found. Enable the Windows OpenSSH Client feature first."
    }
}

$SshArgs = @(
    "-p", [string]$Port,
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=10",
    "-o", "ServerAliveCountMax=3"
)
$ScpArgs = @("-P", [string]$Port, "-o", "ConnectTimeout=10")
if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
    $resolvedIdentity = (Resolve-Path -LiteralPath $IdentityFile).Path
    $SshArgs += @("-i", $resolvedIdentity)
    $ScpArgs += @("-i", $resolvedIdentity)
}

function Invoke-RemoteScript {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [switch]$AsRoot,
        [switch]$Interactive
    )

    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $shellCommand = if ($AsRoot -and $Interactive) {
        "sudo bash"
    }
    elseif ($AsRoot) {
        "sudo -n bash"
    }
    else {
        "bash"
    }
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | $shellCommand"
    $invokeSshArgs = @($SshArgs)
    if ($Interactive) {
        $invokeSshArgs += "-tt"
    }
    & ssh @invokeSshArgs $Target $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed with exit code $LASTEXITCODE."
    }
}

function Find-RemotePluginDirectory {
    $pluginRoot = "/home/$UserName/homebrew/plugins"
    $script = @"
set +e
PLUGIN_ROOT='$pluginRoot'
for manifest in "`$PLUGIN_ROOT"/*/plugin.json; do
    test -r "`$manifest" || continue
    if python3 -c 'import json, sys; raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8")).get("name") == "eGPUBridge" else 1)' "`$manifest" 2>/dev/null; then
        dirname "`$manifest"
    fi
done
"@

    $matches = @(
        Invoke-RemoteScript -Script $script |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    if ($matches.Count -gt 1) {
        throw "Multiple eGPUBridge runtime directories were found: $($matches -join ', '). Pass -RemotePluginDir explicitly."
    }
    if ($matches.Count -eq 0) {
        return $RemoteStateDir
    }

    $resolved = $matches[0]
    if ($resolved -notmatch '^/home/[A-Za-z_][A-Za-z0-9_-]*/homebrew/plugins/[A-Za-z0-9._-]+$') {
        throw "The discovered plugin directory is not a safe Decky path: $resolved"
    }
    return $resolved
}

if ([string]::IsNullOrWhiteSpace($RemotePluginDir)) {
    $RemotePluginDir = Find-RemotePluginDirectory
}

function Protect-DiagnosticFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($IncludeSensitive -or -not (Test-Path -LiteralPath $Path)) {
        return
    }

    $text = Get-Content -LiteralPath $Path -Raw
    $text = [regex]::Replace(
        $text,
        '(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])',
        '<redacted>'
    )
    $text = [regex]::Replace(
        $text,
        '(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9]|\.[0-9])',
        '<redacted>'
    )
    $text = [regex]::Replace($text, '(?i)(?<![\w.-])/home/[^/\s]+', '/home/<redacted>')
    $text = [regex]::Replace(
        $text,
        [regex]::Escape($HostName),
        '<redacted>',
        [Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    Set-Content -LiteralPath $Path -Value $text -Encoding utf8
}

function New-TestSession {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $session = Join-Path $OutputRoot $stamp
    New-Item -ItemType Directory -Path $session -Force | Out-Null

    $commit = (& git -C $RepositoryRoot rev-parse HEAD).Trim()
    $branch = (& git -C $RepositoryRoot branch --show-current).Trim()
    $metadata = [ordered]@{
        started_at = (Get-Date).ToString("o")
        action = $Action
        target = if ($IncludeSensitive) { $Target } else { "<redacted>" }
        remote_plugin_dir = if ($IncludeSensitive) { $RemotePluginDir } else { "/home/<redacted>/homebrew/plugins/$($RemotePluginDir.Split('/')[-1])" }
        remote_state_dir = if ($IncludeSensitive) { $RemoteStateDir } else { "/home/<redacted>/homebrew/plugins/$($RemoteStateDir.Split('/')[-1])" }
        branch = $branch
        commit = $commit
        sensitive_identifiers_included = [bool]$IncludeSensitive
    }
    $metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $session "session.json") -Encoding utf8
    return $session
}

function Save-Snapshot {
    param(
        [Parameter(Mandatory = $true)][string]$SessionDirectory,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $output = Join-Path $SessionDirectory "$Name.txt"
    $script = @"
set +e
PLUGIN_DIR='$RemotePluginDir'
STATE_DIR='$RemoteStateDir'
echo '===== TIME ====='
date --iso-8601=seconds
echo '===== SYSTEM ====='
uname -a
echo '===== SESSION ====='
systemctl --user is-active gamescope-session.target 2>&1
systemctl --user show gamescope-session.service -p ActiveState -p SubState -p MainPID 2>&1
pgrep -a gamescope 2>&1
echo '===== GPU / PCI ====='
lspci -nnk 2>&1 | grep -A3 -Ei 'VGA|Display|3D|USB4|Thunderbolt'
echo '===== DRM CONNECTORS ====='
for status in /sys/class/drm/card*-*/status; do
    [ -r "`$status" ] || continue
    printf '%s=' "`$(basename "`$(dirname "`$status")")"
    cat "`$status"
done
echo '===== PLUGIN FILES ====='
test -d "`$PLUGIN_DIR" && ls -ld "`$PLUGIN_DIR" || echo 'plugin directory missing'
echo '===== PLUGIN STATE ====='
test -d "`$STATE_DIR" && ls -ld "`$STATE_DIR" || echo 'plugin state directory missing'
for file in output_order.conf prefer_vk_device.conf gamescope_mode.conf display_transition.json; do
    echo "--- `$file ---"
    if test -r "`$STATE_DIR/`$file"; then
        echo "source=`$STATE_DIR/`$file"
        cat "`$STATE_DIR/`$file"
    elif test -r "`$PLUGIN_DIR/`$file"; then
        echo "source=`$PLUGIN_DIR/`$file"
        cat "`$PLUGIN_DIR/`$file"
    else
        echo 'missing'
    fi
done
echo '===== REDACTED PLUGIN DIAGNOSTICS ====='
if test -r "`$PLUGIN_DIR/main.py"; then
    cd "`$PLUGIN_DIR"
    python3 -c 'import json, main; print(json.dumps(main.collect_diagnostics(), indent=2, ensure_ascii=False, default=str))' 2>&1
else
    echo 'main.py missing'
fi
echo '===== RECENT RELEVANT JOURNAL ====='
journalctl -b --since '15 minutes ago' --no-pager -o short-iso 2>&1 | grep -Ei 'egpubridge|egpu|gamescope|amdgpu|drm|hdmi|display|connector|usb4|thunderbolt|pcie|aer|gpu reset|device lost' | tail -n 300
"@

    Write-Host "Saving $Name snapshot to $output"
    Invoke-RemoteScript -Script $script 2>&1 | Set-Content -LiteralPath $output -Encoding utf8
    Protect-DiagnosticFile -Path $output
}

function Invoke-Preflight {
    $script = @"
set +e
PLUGIN_DIR='$RemotePluginDir'
STATE_DIR='$RemoteStateDir'
echo 'eGPUBridge remote-test preflight'
HOST_NAME=`$(cat /etc/hostname 2>/dev/null)
if test -z "`$HOST_NAME"; then
    HOST_NAME=`$(uname -n 2>/dev/null)
fi
echo "user=`$(id -un) uid=`$(id -u) host=`$HOST_NAME"
for tool in bash base64 python3 journalctl systemctl pgrep lspci; do
    if command -v "`$tool" >/dev/null 2>&1; then
        echo "OK tool `$tool"
    else
        echo "MISSING tool `$tool"
    fi
done
if test -r "`$PLUGIN_DIR/plugin.json" && test -r "`$PLUGIN_DIR/main.py"; then
    echo "OK plugin_runtime_dir `$PLUGIN_DIR"
else
    echo "MISSING plugin_runtime_files `$PLUGIN_DIR"
fi
if test -d "`$STATE_DIR"; then
    echo "OK plugin_state_dir `$STATE_DIR"
else
    echo "NOTE plugin_state_dir missing `$STATE_DIR"
fi
echo "gamescope_target=`$(systemctl --user is-active gamescope-session.target 2>/dev/null || true)"
pgrep -a gamescope 2>/dev/null || echo 'gamescope process not visible'
if sudo -n true >/dev/null 2>&1; then
    echo 'OK passwordless_sudo'
else
    echo 'NOTE passwordless_sudo unavailable; deployment requires -InteractiveSudo in a visible terminal'
fi
"@
    Invoke-RemoteScript -Script $script | ForEach-Object { Write-Host $_ }
}

function Invoke-Capture {
    $session = New-TestSession
    Save-Snapshot -SessionDirectory $session -Name "before"

    $seconds = $DurationMinutes * 60
    $capturePath = Join-Path $session "live.txt"
    $script = @"
set +e
PLUGIN_DIR='$RemotePluginDir'
STATE_DIR='$RemoteStateDir'
DURATION='$seconds'
echo "LIVE_CAPTURE_START `$(date --iso-8601=seconds) duration_seconds=`$DURATION"
(
  timeout --signal=INT "`$DURATION" journalctl -b -f -n 0 --no-pager -o short-iso 2>&1 |
    grep --line-buffered -Ei 'egpubridge|egpu|gamescope|plugin_loader|amdgpu|drm|hdmi|display|connector|usb4|thunderbolt|pcie|aer|gpu reset|device lost' |
    sed -u 's/^/[journal] /'
) &
JOURNAL_PID=`$!
PLUGIN_LOGS=()
for log_path in "`$PLUGIN_DIR/plugin.log" "`$STATE_DIR/plugin.log"; do
  test -r "`$log_path" || continue
  if test "`${#PLUGIN_LOGS[@]}" -eq 0 || test "`${PLUGIN_LOGS[0]}" != "`$log_path"; then
    PLUGIN_LOGS+=("`$log_path")
  fi
done
if test "`${#PLUGIN_LOGS[@]}" -gt 0; then
  timeout --signal=INT "`$DURATION" tail -n 0 -F "`${PLUGIN_LOGS[@]}" 2>&1 | sed -u 's/^/[plugin] /' &
  PLUGIN_PID=`$!
else
  echo '[plugin] no readable plugin.log found'
  PLUGIN_PID=''
fi
wait "`$JOURNAL_PID"
test -z "`$PLUGIN_PID" || wait "`$PLUGIN_PID"
echo "LIVE_CAPTURE_END `$(date --iso-8601=seconds)"
"@

    Write-Host "Live capture started for $DurationMinutes minute(s). Perform the display tests on the Ally now."
    Invoke-RemoteScript -Script $script 2>&1 | Tee-Object -FilePath $capturePath
    Protect-DiagnosticFile -Path $capturePath
    Save-Snapshot -SessionDirectory $session -Name "after"
    Write-Host "Capture complete: $session"
}

function Invoke-Deploy {
    if (-not $ConfirmDeploy) {
        throw "Deploy changes the plugin on the Ally. Re-run with -ConfirmDeploy after checking the target."
    }
    if (-not $InteractiveSudo) {
        try {
            Invoke-RemoteScript -Script "true" -AsRoot | Out-Null
        }
        catch {
            throw "Deployment needs root access. Re-run in a visible terminal with -InteractiveSudo, or configure passwordless sudo for this operation."
        }
    }

    Write-Host "Running local verification before deployment..."
    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) {
        $codexPnpm = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
        if (Test-Path -LiteralPath $codexPnpm -PathType Leaf) {
            $pnpmCommand = Get-Command -Name $codexPnpm -ErrorAction Stop
        }
    }
    if (-not $pnpmCommand) {
        throw "pnpm was not found. Install pnpm or add its directory to PATH before deployment."
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "python was not found. Install Python 3 or add it to PATH before deployment."
    }

    & $pnpmCommand.Source --dir $RepositoryRoot build:check
    if ($LASTEXITCODE -ne 0) { throw "Frontend build verification failed." }
    & $pythonCommand.Source -m unittest discover -s (Join-Path $RepositoryRoot "tests") -v
    if ($LASTEXITCODE -ne 0) { throw "Backend regression tests failed." }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archive = Join-Path ([IO.Path]::GetTempPath()) "egpubridge-$stamp.tar.gz"
    $remoteArchive = "/tmp/egpubridge-$stamp.tar.gz"
    $packageItems = @(
        "dist", "src", "scripts", "docs", "main.py", "package.json", "pnpm-lock.yaml",
        "plugin.json", "rollup.config.js", "tsconfig.json", "bin", "LICENSE", "README.md"
    )

    try {
        & tar -C $RepositoryRoot -czf $archive @packageItems
        if ($LASTEXITCODE -ne 0) { throw "Could not create deployment archive." }

        & scp @ScpArgs $archive "${Target}:$remoteArchive"
        if ($LASTEXITCODE -ne 0) { throw "Could not upload deployment archive." }

        $script = @"
set -Eeuo pipefail
PLUGIN_DIR='$RemotePluginDir'
STATE_DIR='$RemoteStateDir'
ARCHIVE='$remoteArchive'
STAMP='$stamp'
PARENT=`$(dirname "`$PLUGIN_DIR")
STAGING="`$PLUGIN_DIR.staging-`$STAMP"
BACKUP="`$PLUGIN_DIR.backup-`$STAMP"
rollback() {
  if test ! -d "`$PLUGIN_DIR" && test -d "`$BACKUP"; then mv "`$BACKUP" "`$PLUGIN_DIR"; fi
}
trap rollback ERR
mkdir -p "`$PARENT"
rm -rf "`$STAGING"
mkdir "`$STAGING"
tar -xzf "`$ARCHIVE" -C "`$STAGING"
if test -d "`$PLUGIN_DIR"; then mv "`$PLUGIN_DIR" "`$BACKUP"; fi
mv "`$STAGING" "`$PLUGIN_DIR"
if test -d "`$BACKUP"; then
  for file in output_order.conf prefer_vk_device.conf gamescope_mode.conf tv_control_automation.json hotkey_settings.json; do
    if test "`$STATE_DIR" != "`$PLUGIN_DIR" && test -f "`$STATE_DIR/`$file"; then
      cp -p "`$STATE_DIR/`$file" "`$PLUGIN_DIR/`$file"
    elif test -f "`$BACKUP/`$file"; then
      cp -p "`$BACKUP/`$file" "`$PLUGIN_DIR/`$file"
    fi
  done
fi
chmod +x "`$PLUGIN_DIR/bin/gamescope" "`$PLUGIN_DIR/bin/"*.sh 2>/dev/null || true
rm -f "`$ARCHIVE"
trap - ERR
echo "DEPLOYED backup=`$BACKUP"
if systemctl restart plugin_loader.service; then
  echo 'RESTARTED plugin_loader.service'
else
  echo 'DEPLOYED but plugin_loader restart needs to be run manually'
fi
"@
        Invoke-RemoteScript -Script $script -AsRoot -Interactive:$InteractiveSudo | ForEach-Object { Write-Host $_ }
    }
    finally {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
}

switch ($Action) {
    "Preflight" { Invoke-Preflight }
    "Snapshot" {
        $session = New-TestSession
        Save-Snapshot -SessionDirectory $session -Name "snapshot"
        Write-Host "Snapshot complete: $session"
    }
    "Capture" { Invoke-Capture }
    "Deploy" { Invoke-Deploy }
}
