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

    [ValidateRange(1, 120)]
    [int]$DurationMinutes = 15,

    [string]$OutputRoot = "",

    [switch]$IncludeSensitive,
    [switch]$ConfirmDeploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($RemotePluginDir)) {
    $RemotePluginDir = "/home/$UserName/homebrew/plugins/eGPUBridge"
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
    param([Parameter(Mandatory = $true)][string]$Script)

    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | bash"
    & ssh @SshArgs $Target $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed with exit code $LASTEXITCODE."
    }
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
        '(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])',
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
        remote_plugin_dir = if ($IncludeSensitive) { $RemotePluginDir } else { "/home/<redacted>/homebrew/plugins/eGPUBridge" }
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
for file in output_order.conf prefer_vk_device.conf gamescope_mode.conf display_transition.json; do
    echo "--- `$file ---"
    test -r "`$PLUGIN_DIR/`$file" && cat "`$PLUGIN_DIR/`$file" || echo 'missing'
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
echo 'eGPUBridge remote-test preflight'
echo "user=`$(id -un) uid=`$(id -u) host=`$(hostname)"
for tool in bash base64 python3 journalctl systemctl pgrep lspci; do
    if command -v "`$tool" >/dev/null 2>&1; then
        echo "OK tool `$tool"
    else
        echo "MISSING tool `$tool"
    fi
done
if test -d "`$PLUGIN_DIR"; then
    echo "OK plugin_dir `$PLUGIN_DIR"
else
    echo "MISSING plugin_dir `$PLUGIN_DIR"
fi
echo "gamescope_target=`$(systemctl --user is-active gamescope-session.target 2>/dev/null || true)"
pgrep -a gamescope 2>/dev/null || echo 'gamescope process not visible'
if sudo -n true >/dev/null 2>&1; then
    echo 'OK passwordless_sudo'
else
    echo 'NOTE passwordless_sudo unavailable; automatic plugin_loader restart may need manual approval'
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
DURATION='$seconds'
echo "LIVE_CAPTURE_START `$(date --iso-8601=seconds) duration_seconds=`$DURATION"
(
  timeout --signal=INT "`$DURATION" journalctl -b -f -n 0 --no-pager -o short-iso 2>&1 |
    grep --line-buffered -Ei 'egpubridge|egpu|gamescope|plugin_loader|amdgpu|drm|hdmi|display|connector|usb4|thunderbolt|pcie|aer|gpu reset|device lost' |
    sed -u 's/^/[journal] /'
) &
JOURNAL_PID=`$!
if test -r "`$PLUGIN_DIR/plugin.log"; then
  timeout --signal=INT "`$DURATION" tail -n 0 -F "`$PLUGIN_DIR/plugin.log" 2>&1 | sed -u 's/^/[plugin] /' &
  PLUGIN_PID=`$!
else
  echo '[plugin] plugin.log is not readable'
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

    Write-Host "Running local verification before deployment..."
    & pnpm --dir $RepositoryRoot build:check
    if ($LASTEXITCODE -ne 0) { throw "Frontend build verification failed." }
    & python -m unittest discover -s (Join-Path $RepositoryRoot "tests") -v
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
    test ! -f "`$BACKUP/`$file" || cp -p "`$BACKUP/`$file" "`$PLUGIN_DIR/`$file"
  done
fi
chmod +x "`$PLUGIN_DIR/bin/gamescope" "`$PLUGIN_DIR/bin/"*.sh 2>/dev/null || true
rm -f "`$ARCHIVE"
trap - ERR
echo "DEPLOYED backup=`$BACKUP"
if sudo -n systemctl restart plugin_loader.service; then
  echo 'RESTARTED plugin_loader.service'
else
  echo 'DEPLOYED but plugin_loader restart needs to be run manually'
fi
"@
        Invoke-RemoteScript -Script $script | ForEach-Object { Write-Host $_ }
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
