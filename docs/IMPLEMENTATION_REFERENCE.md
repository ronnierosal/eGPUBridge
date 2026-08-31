# eGPUBridge Implementation Reference

This is a factual reference for the validated `codex/core-native-stage2` build on
an ASUS ROG Ally X running SteamOS with a GPD G1. It describes the implementation
that was tested on 2026-08-30; it is not an HDM architecture proposal.

## Hardware detection and identity

- `scan_cards()` enumerates `/sys/class/drm/card[0-9]`. Each card's `device`
  symlink supplies PCI address, vendor/device IDs, `boot_vga`, driver, and DRM
  connector state. Card numbers are enumeration results, not stable identity.
- A non-boot VGA card is an eGPU candidate. A candidate with a connected connector
  is preferred, but mutations require a stable PCI address and exact identity.
- The validated G1 profile proves all of the following: RX 7600M XT GPU
  `1002:7480`; removable Intel Titan Ridge bridge `8086:15ef` with bridge class
  `0604`; AMD HDMI audio `1002:ab30`; Intel xHCI `8086:15f0`; and exactly one
  authorized USB4 device reported as Intel `Tapex Creek`.
- On the final test boot the GPU was `0000:08:00.0` and the removable root was
  `0000:04:00.0`. These addresses must be rediscovered rather than hard-coded.
- A fully proved identity is persisted in `egpu_identity.json`. It includes the
  profile, PCI/vendor/device/root values and a SHA-256 of the USB4 unique ID. The
  raw unique ID is not persisted or returned in normal diagnostics.
- A saved identity must match exactly before a later switch. A missing, ambiguous,
  changed, or incompletely proved G1 fails closed.

## Display detection

- The internal panel is the connected `eDP-*` connector found under
  `/sys/class/drm`. The tested panel is `card0-eDP-1`. A fallback may identify an
  eDP path for read-only status, but connector mutation obtains the live connector
  ID from `modetest` and refuses to guess when it cannot be found.
- External discovery scans generic `HDMI` and `DP` DRM connectors, excluding
  eDP. A connected HDMI connector is preferred, followed by another connected
  external connector. The tested TV was `card1-HDMI-A-1`.
- Connector names and card numbers can change across boots or enumeration. Earlier
  captures observed `HDMI-A-2`; live sysfs and Gamescope state are authoritative.
- EDID supplies the monitor name, while `modetest` supplies connector IDs, DPMS
  state, and physical modes. The final Samsung TV pass selected `3840x2160@60`.
- External DPMS is enabled before an external restart and disabled after internal
  restore. The internal backlight and eDP DPMS are restored before returning to
  the Ally panel.
- A connected connector is not assumed active. Active state is verified from the
  live Gamescope `-O`/`--prefer-output` argument and selected Vulkan device.

## Steam game detection

- The guard queries the active Gamescope user's systemd scopes with:
  `systemctl --user list-units --type=scope --state=running`.
- Supported legacy forms are `app-steam-<appid>.scope` and
  `steam-app-<appid>.scope`.
- Current tested SteamOS uses `app-steam-app<appid>-<instance>.scope`, for example
  `app-steam-app2909400-43899.scope`.
- Any otherwise unparsed `app-steam-app*.scope` is treated as a running game. If
  the systemd query itself fails, the switch fails closed with
  `running_game_check_failed`.
- A transition that would restart Game Mode is blocked while a game scope exists.
  The native UI reports `Display switch blocked`; it does not offer a normal-use
  override.

## Gamescope switching

- eGPUBridge uses its Gamescope wrapper configuration and a reversible user-service
  integration. It does not overwrite the SteamOS-owned Gamescope session script.
- TV mode writes the discovered connector to the output order and sets the exact
  eGPU Vulkan ID, producing the tested arguments
  `-O HDMI-A-1 --prefer-vk-device 1002:7480`.
- Portable mode writes `-O *,eDP-1`, disables the persisted eGPU preference, and
  removes `MESA_VK_DEVICE_SELECT` from the Gamescope user's systemd environment.
- A restart is required when startup-time output or Vulkan-device arguments must
  change. An already-satisfied request writes/normalizes desired configuration but
  skips the restart. Hardware proved that this keeps the Gamescope PID unchanged.
- Before restart, the backend validates identity, connector, integration, and the
  running-game guard. It then writes a durable pending transition and returns an
  accepted asynchronous handoff to Decky.
- Readiness waits for a new Gamescope PID whose exact output, Vulkan device, and
  explicitly requested mode match the desired state. Fixed post-restart sleeps are
  not used. Completed transitions are recorded with measured total time.
- A stale external transition is eligible for automatic internal rollback after
  the reconciliation timeout. Controlled rollback failure injection remains
  unvalidated on hardware.
- Restarting Gamescope tears down the current Game Mode session and can close a
  running game. That consequence is why game detection must remain fail-closed.

## Diagnostics and remote testing

- `scripts/ally-remote-test.ps1` supports preflight, snapshot, timed live capture,
  and transactional deployment from a separate Windows machine over SSH.
- Snapshots collect Gamescope arguments/PIDs, DRM connectors, PCI inventory,
  plugin state, redacted diagnostics, and a filtered 15-minute journal window.
- Live capture follows the plugin log and relevant journal entries, then saves
  before/after snapshots. Local identifiers, home paths, IP addresses, USB unique
  IDs, and configured TV addresses are redacted by default.
- `collect_pcie_link_health()` queries the kernel journal and summarizes G1-related
  AER severity, layer, error type, affected PCI function, recovery failure, and
  xHCI `can't recover` records. Useful raw tools include `lspci`, `/sys/class/drm`,
  `modetest`, `pgrep -af gamescope`, `systemctl --user`, and `journalctl -k`.
- Final evidence is stored in `test-results/20260830-185523`,
  `test-results/20260830-185650`, and `test-results/20260830-190017`.

## Safety lessons and limitations

- Physical G1 hot-unplug is unsafe on the tested stack. A prior controlled release
  blocked in AMDGPU/pciehp teardown and contributed to a later boot hang. Shut the
  Ally down before disconnecting the G1.
- Active eGPU workloads are not assumed migratable. This build does not migrate a
  running game between the iGPU and eGPU.
- Unknown game state fails closed. Unknown or changed eGPU identity also fails
  closed.
- Display switching is desired-state driven and post-verified. A connected cable
  alone is not proof that the requested state is active.
- Avoid unnecessary Gamescope restarts. They disrupt Game Mode and repeatedly
  coincided with G1 PCIe/AER and xHCI recovery noise.
- The tested USB4 path remained degraded despite successful display transitions.
  Cable, port, firmware, and broader hardware comparisons remain open.
- G1 rendering to the Ally panel is probable from informal performance/fan
  observations but not proved; see EGB-035.
