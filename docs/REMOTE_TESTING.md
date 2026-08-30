# Remote ROG Ally X testing

Codex does not need to be installed on the Ally. The development computer can
deploy the plugin, run read-only checks, and capture logs over SSH while the Ally
stays in Game Mode.

## One-time Ally setup

1. Enable an SSH server on the Ally and keep it connected to the same trusted
   network as the development computer.
2. Find the Ally's hostname or IP address and confirm its Linux username.
3. Prefer an SSH key. Do not place passwords or private keys in this repository.
4. Keep the Ally connected to Wi-Fi while changing displays so SSH is not tied to
   the GPD G1's USB or Ethernet path.

The runner discovers the active runtime directory from the Decky plugin manifests,
including versioned folders such as `eGPUBridge-v0.3.alfa`. The conventional
`/home/<username>/homebrew/plugins/eGPUBridge` folder is treated separately as a
legacy state directory so existing display settings and logs can be migrated.
Use `-RemotePluginDir` or `-RemoteStateDir` only when automatic discovery does not
match a custom installation.

## Commands from Windows PowerShell

Run these from the repository root. Replace the example address and username.

```powershell
# Read-only connection and dependency check
./scripts/ally-remote-test.ps1 -Action Preflight -HostName 192.168.1.50 -UserName deck -IdentityFile "$env:USERPROFILE\.ssh\rog-ally-x"

# One read-only snapshot
./scripts/ally-remote-test.ps1 -Action Snapshot -HostName 192.168.1.50 -UserName deck -IdentityFile "$env:USERPROFILE\.ssh\rog-ally-x"

# Before/during/after capture while testing for 15 minutes
./scripts/ally-remote-test.ps1 -Action Capture -HostName 192.168.1.50 -UserName deck -IdentityFile "$env:USERPROFILE\.ssh\rog-ally-x" -DurationMinutes 15
```

Captured sessions are stored under `test-results/<timestamp>/`, which Git ignores.
Reports redact the host/IP, home username, IPv4 addresses, and MAC addresses by
default. Add `-IncludeSensitive` only for a private local capture when the exact
network identifiers are needed.

## Deploying a test branch

Deployment is intentionally separate from capture and requires an explicit flag:

```powershell
./scripts/ally-remote-test.ps1 -Action Deploy -HostName 192.168.1.50 -UserName deck -IdentityFile "$env:USERPROFILE\.ssh\rog-ally-x" -ConfirmDeploy -InteractiveSudo
```

The runner performs the local build and backend tests first, uploads a temporary
archive, moves the discovered runtime plugin to a timestamped backup, migrates
display and hotkey configuration from the runtime or legacy state directory,
installs the new tree, and attempts to restart Decky. If
passwordless `sudo` is unavailable, run the command in a visible terminal with
`-InteractiveSudo` and enter the SteamOS password at its prompt. Without that
switch, deployment fails before upload instead of leaving a partial installation.

## Planned hardware sequence

1. Run `Preflight` with the GPD G1 disconnected.
2. Start `Capture`, connect the G1, and wait for the external connector to appear.
3. In eGPUBridge, collect diagnostics and switch to the external display.
4. Confirm the TV picture, resolution, refresh rate, audio, controller navigation,
   and that the expected GPU renders Game Mode.
5. Switch back to the internal panel before disconnecting the G1.
6. Let capture finish and review `before.txt`, `live.txt`, and `after.txt` together.

Do not use the disabled Safe Unplug, fan-control, overclock, or NVIDIA-driver
features during this test cycle.
