# eGPUBridge review backlog

Last reviewed: 2026-08-30

This document records the issues found while reviewing the fork for a ROG Ally X
and GPD G1. It is a working backlog, not a claim that every item is reproduced on
hardware. Hardware-dependent items should remain open until verified over SSH on
the target system.

Priority meanings:

- P0: address before broad hardware testing
- P1: serious safety or correctness risk
- P2: reliability, portability, or maintainability work
- P3: useful follow-up work

## P0 - pre-hardware safety and switching

### EGB-001 - Verify the Gamescope integration is actually active

Status: Implemented; initial ROG Ally X/GPD G1 hardware validation passed 2026-08-30

The backend now installs a user-systemd environment drop-in that places the small
`bin/gamescope` argument shim ahead of the stock executable. It refuses to switch
if the integration cannot be installed or the user service is unavailable, then
verifies the new live Gamescope command line before disabling the internal panel.

Relevant code:

- [`main.py`](../main.py#L3133)
- [`bin/gamescope`](../bin/gamescope)

Acceptance criteria:

- Preflight identifies the live Gamescope PID and command line.
- Switching is refused if the requested configuration cannot be consumed.
- Post-start verification confirms the selected GPU, connector, and mode.
- Integration does not overwrite the complete SteamOS-owned session script.

### EGB-002 - Make the Game Mode reload transactional and event-driven

Status: Partially implemented; external/internal round trip passed hardware validation,
asynchronous RPC handoff remains pending

The demo video shows that selecting the external screen restarts the Game Mode
session. This is not a device reboot: the plugin calls
`systemctl --user restart gamescope-session.target`. A restart remains required
when changing Gamescope startup arguments such as `-O` and
`--prefer-vk-device`. This branch now skips an already-satisfied request, blocks
when a Steam game is running, records a durable transition, and replaces the
fixed six-second sleep with bounded new-PID and exact-argument verification.

The remaining work is to acknowledge and schedule the restart without keeping
the Decky RPC open while its own UI is torn down, validate the returning Decky UI
on hardware, and add automatic internal-state rollback when a transition cannot
be reconciled after startup.

The 2026-08-30 hardware pass confirmed this remaining RPC issue: the switch
completed and the returning UI worked, but Decky's websocket router logged that
it dropped the successful RPC result because the restart had already disconnected
the calling socket. The user-visible transition is functional; asynchronous
acknowledgement is still needed to make the handoff clean and observable.

Relevant code:

- [`main.py`](../main.py#L3162)
- [`main.py`](../main.py#L3247)
- [`main.py`](../main.py#L3543)
- [`dist/index.js`](../dist/index.js#L1506)
- [`dist/index.js`](../dist/index.js#L2367)

Recommended design:

1. Build a desired-state fingerprint from exact PCI GPU, connector, mode, and
   Gamescope arguments. Skip the restart when it already matches the live state.
2. Refuse or require an explicit warning when a game is running.
3. Write and validate all configuration, plus a transition token, before stopping
   the session.
4. Acknowledge the UI action, then schedule the restart asynchronously so the
   Decky RPC does not wait through its own teardown.
5. Replace `sleep(6)` with a bounded readiness watcher for a new Gamescope PID,
   active `gamescope-session.target`, selected GPU, active connector, and the
   returning Steam/Decky UI.
6. Reconcile the transition token when the plugin starts again, report measured
   timings, and restore the internal configuration if verification times out.

This cannot eliminate the visible Game Mode handoff while Gamescope requires
startup-time GPU selection. It can eliminate redundant restarts, remove the
arbitrary wait, shorten the common path, and make failure recovery deterministic.

Video reference:

- https://www.youtube.com/watch?v=U2BGA6zEtAk&t=745s

### EGB-003 - Replace both unsafe disconnect implementations

Status: Mitigated - both UI and backend controls are disabled until fixed

`prepare_for_unplug` restarts SDDM, sleeps eight seconds, and announces readiness
without proving that the internal panel is active or that the eGPU is idle. The
separate `safe_disconnect` path selects the first non-boot GPU and first authorized
Thunderbolt device, which may not be the GPD G1. It also does not inspect mounted
storage behind the G1 USB hub/card reader.

Relevant code:

- [`main.py`](../main.py#L1285)
- [`main.py`](../main.py#L1337)
- [`main.py`](../main.py#L3435)
- [`dist/index.js`](../dist/index.js#L3854)

Acceptance criteria:

- One authoritative unplug workflow.
- Exact selected GPU and parent USB4/Thunderbolt topology are required.
- Enumerate child PCI, USB, block, filesystem, and mount dependencies.
- Abort on mounted storage, active processes, or any display-restore failure.
- Verify the internal output before allowing physical removal.

## P1 - privileged hardware controls

### EGB-004 - Use stable external-GPU identity

Status: Open

The code treats every DRM GPU with `boot_vga != 1` as an eGPU. This can select a
built-in dGPU, virtual adapter, or unrelated display device. Persist an exact PCI
address and verify its hotplug/topology relationship before any mutation.

Relevant code: [`main.py`](../main.py#L548)

### EGB-005 - Disable or redesign fan control

Status: Mitigated - UI and backend controls are disabled until GPD G1 sysfs is captured

The code writes `fan1_enable`; Linux PWM control normally uses `pwm1_enable`.
Manual mode permits PWM zero and has no crash/unload watchdog that restores the
previous automatic state.

Relevant code: [`main.py`](../main.py#L6232)

Acceptance criteria include driver-specific capability detection, safe minimum
PWM, temperature limits, previous-state restoration, and a fail-safe watchdog.

### EGB-006 - Validate and roll back OD clock/voltage writes

Status: Mitigated - UI and backend controls are disabled until fixed

The backend parses supported ranges but does not enforce them. It can return
`ok: true` when every sysfs write failed and has no rollback for partial writes.

Relevant code:

- [`main.py`](../main.py#L6391)
- [`main.py`](../main.py#L6401)

### EGB-007 - Remove the in-plugin NVIDIA driver installer

Status: Mitigated - UI is hidden and all driver-mutation RPCs fail closed

The installer deletes Pacman and NVIDIA state, removes documentation directories,
replaces directories with symlinks, uses hard-coded Neptune headers, and can
report success when `nvidia-smi` verification fails. Driver installation should
not be exposed as a Decky RPC.

Relevant code: [`main.py`](../main.py#L6470)

### EGB-008 - Add server-side authorization for privileged RPC actions

Status: Open

Frontend confirmation is not an authorization boundary. Destructive actions need
a short-lived server-side token tied to a preview, exact device identity, action,
and expiry. Unused privileged endpoints should be removed.

Relevant code:

- [`plugin.json`](../plugin.json)
- [`main.py`](../main.py#L6457)
- [`dist/index.js`](../dist/index.js#L1555)

## P2 - reliability and portability

### EGB-009 - Remove the fixed internal connector ID fallback

Status: Implemented in `codex/safe-switching-foundation`; hardware validation pending

When detection fails, the backend guesses connector ID `108`. It should fail
closed and roll back any framebuffer/backlight changes instead.

Relevant code: [`main.py`](../main.py#L1037)

### EGB-010 - Capture the DRM baseline before PCI rescan

Status: Open

The polling helper records its baseline after the rescan call. A GPU that appears
immediately can therefore be considered part of the baseline and the poll times
out. Capture the baseline before rescan and wait for an exact expected PCI device.

Relevant code:

- [`main.py`](../main.py#L1270)
- [`main.py`](../main.py#L1481)

### EGB-011 - Remove `/home/deck` assumptions

Status: Open

TV configuration, ADB keys, helper scripts, and symlinks contain hard-coded
`/home/deck` paths. Derive one runtime context containing username, UID, home,
runtime directory, and plugin directory, then pass it to every subsystem.

### EGB-012 - Redact diagnostics by default

Status: Implemented in `codex/remote-test-harness`; review pending

Diagnostic reports currently include TV IP/MAC configuration and broad journal
content. Redact local identifiers by default and make inclusion explicit.

Diagnostic JSON, recent-event output, and encoded support reports now redact
hostname, home username, IPv4 addresses, and MAC addresses by default. The
Windows SSH harness applies the same policy to saved captures unless the operator
explicitly supplies `-IncludeSensitive`.

Relevant code: [`main.py`](../main.py#L4495)

### EGB-013 - Remove runtime monkey-patching and split `main.py`

Status: Open

`main.py` is over 6,800 lines and replaces `Plugin` methods later through runtime
assignments. This makes it easy to edit an implementation that is no longer the
authoritative path. Split display, hardware, diagnostics, tuning, TV, and driver
operations into modules and define each RPC once.

Relevant code: [`main.py`](../main.py#L4835)

### EGB-014 - Make the frontend reproducible

Status: Implemented in `codex/decky-native-foundation`; hardware validation pending

The repository previously had no source-to-dist verification. The native
foundation makes `src/index.tsx` authoritative, generates `dist/index.js` through
the official Decky Rollup preset, and makes CI fail when generated output drifts.

### EGB-015 - Replace the copied full Gamescope session script

Status: Implemented with a small argument shim and user-systemd drop-in; hardware validation pending

The bundled wrapper is a complete distribution session script and can drift from
SteamOS. It also contains unrelated low-disk cleanup logic. Replace it with the
smallest supported integration layer or environment/drop-in mechanism.

Relevant code: [`bin/gamescope`](../bin/gamescope)

## P3 - verification and release hygiene

### EGB-016 - Expand deterministic tests

Status: In progress - deterministic coverage expanded from 7 to 27 tests

Add tests for exact device selection, topology-safe disconnect, transition-state
recovery, reload idempotency, connector detection failures, tuning bounds,
partial-write failures, redaction, and packaging.

### EGB-017 - Improve release provenance

Status: Implemented in `codex/remote-test-harness`; review pending

Publish once per tag, verify tag/version consistency, add checksums, and document
the source/version of bundled Android platform tools.

The release workflow now creates each release in one upload step, validates the
tag against the package version, fails on missing artifacts, and publishes a
SHA-256 checksum. `docs/THIRD_PARTY.md` records Android Platform-Tools provenance
and the package check requires its recorded revision and notice.

### EGB-018 - Modernize the frontend with Decky UI and Decky API

Status: Native build and API foundation implemented in `codex/decky-native-foundation`; visual migration remains deferred

The frontend uses some Decky components, but it also contains hundreds of inline
style declarations, multiple embedded `<style>` blocks, extensive `!important`
overrides, custom focus behavior, and hand-built versions of standard controls.
The foundation now uses the current Decky build template, direct `@decky/ui`
imports, and RPC helpers from `@decky/api`. After the major correctness and
safety issues are validated, migrate the remaining hand-built controls and
styling incrementally.

Recommended replacements include:

- `ButtonItem` or `DialogButton` for custom action-button wrappers.
- `ToggleField` for hand-built toggle rows.
- `Dropdown` for performance and GPU-profile selectors.
- `SliderField` for tuning ranges.
- `Field`, `PanelSection`, and `PanelSectionRow` for standard layout and status rows.
- Continue replacing the transitional generic UI call helper with direct typed
  route helpers from the new RPC registry.

Retain only small, isolated plugin-specific styling where Decky has no suitable
element, such as GPU status indicators, compact hardware layouts, diagnostic
output, or the specialized IP roller. Do not combine this visual refactor with
the active switching-safety changes.

Acceptance criteria:

- A reproducible TypeScript/Rollup build based on the current Decky template.
- Standard controls inherit Decky styling, theming, and gamepad focus behavior.
- Embedded remote font imports and broad Steam/Decky CSS overrides are removed.
- All existing actions and backend RPC behavior remain functionally equivalent.
- Gamepad navigation and each control are validated on the ROG Ally X before the
  legacy compatibility and styling layers are removed.

Foundation completed on the feature branch:

- Official `@decky/rollup`, `@decky/ui`, and `@decky/api` dependencies with a
  locked pnpm toolchain.
- `src/index.tsx` is authoritative and reproducibly generates `dist/index.js`.
- Native default plugin export replaces `window.eGPUBridgePlugin` registration.
- A typed 35-route RPC registry replaces direct legacy `callPluginMethod` use.
- `api_version: 1` positional-call compatibility is checked against the Python
  plugin instance in deterministic tests.
- CI type-checks, rebuilds, detects generated-output drift, and verifies the
  frontend/backend route contract.

Relevant code: [`src/index.tsx`](../src/index.tsx)

### EGB-019 - Separate the Decky runtime directory from legacy plugin state

Status: Implemented and runtime discovery verified on ROG Ally X; deployment migration pending

Decky can install a release into a versioned directory such as
`eGPUBridge-v0.3.alfa` while the installed backend continues to store settings and
logs under `eGPUBridge`. The first SSH harness treated the state directory as the
runtime, so diagnostics missed `main.py` and deployment would have replaced the
wrong tree. The harness now discovers the runtime by manifest name, captures both
locations, and migrates configuration from the legacy state directory.

Relevant code: [`scripts/ally-remote-test.ps1`](../scripts/ally-remote-test.ps1)

### EGB-020 - Sanitize Decky's bundled library environment for system commands

Status: Implemented with regression coverage; hardware validation pending

Live diagnostics showed `pacman -Q mesa` loading a PyInstaller copy of
`libssl.so.3` from `/tmp/_MEI*` and failing its SteamOS OpenSSL version check.
System command runners now remove Decky/PyInstaller library and Python override
variables while retaining the rest of the environment.

Relevant code: [`main.py`](../main.py)

### EGB-021 - Reject textual `modetest` write failures

Status: Implemented with regression coverage; hardware validation pending

On the Ally, `modetest` returned exit code zero while reporting that the internal
connector DPMS write failed with `Permission denied`. The backend therefore marked
the panel-off step successful even though the write failed. Connector writes now
normalize known textual failures into an unsuccessful result and expose the
underlying command result for diagnostics.

Relevant code: [`main.py`](../main.py)

### EGB-022 - Keep deployment backups outside Decky's plugin scan directory

Status: Implemented after live deployment validation

Decky treats every immediate child directory containing a plugin manifest as a
loadable plugin. The first transactional deployment left its timestamped backup
beside the active runtime, causing Decky to load both copies under the same plugin
name and route calls to the old API contract. Deployments now store backups under
`homebrew/plugin-backups/eGPUBridge`, and runtime discovery ignores legacy backup
or staging directory names.

Relevant code: [`scripts/ally-remote-test.ps1`](../scripts/ally-remote-test.ps1)

### EGB-023 - Detect and summarize unstable USB4/PCIe links

Status: Open - reproduced on ROG Ally X/GPD G1 hardware 2026-08-30

The first live hardware pass completed successfully, but the kernel repeatedly
reported PCIe AER errors on the G1's USB4/Thunderbolt path. These included
correctable `BadDLLP` and `BadTLP` events on `0000:05:01.0`, plus non-fatal
uncorrectable `ACSViol` events on `0000:05:02.0`. The attached xHCI device at
`0000:09:00.0` reported that it could not recover. Gamescope remained usable and
the RX 7600M XT rendered a game at a reported steady 60 FPS, so this is a link
health warning rather than a reproduced display-switch failure.

Before changing kernel settings, repeat the test with the cable reseated, a
known-certified USB4 cable, and the other Ally USB4 port. Diagnostics should
count AER events by severity, BDF, and error type; identify the affected parent
topology; and warn when the rate exceeds a small threshold. Live capture should
summarize repeated identical events instead of flooding the operator console.

### EGB-024 - Reconcile powered-off eGPU removal cleanly

Status: Open - reproduced after a successful internal-display restore 2026-08-30

After Gamescope had returned to `-O *,eDP-1` and eGPU preference was disabled,
powering off and disconnecting the G1 produced repeated AMDGPU cleanup failures,
including failed SMU metric reads, `MES failed to respond to msg=REMOVE_QUEUE`,
and `failed to halt cp gfx`. The kernel removed the G1 PCI device after roughly
28 seconds and the internal Gamescope session remained running.

This reinforces EGB-003: a future safe-unplug workflow must prove that no render
queues or processes remain on the exact eGPU, then observe device removal with a
bounded timeout. Diagnostics should distinguish expected hot-removal noise from
a device that remains stuck or disrupts the internal session.

### EGB-025 - Clarify requested render resolution versus physical TV mode

Status: Open - observed on ROG Ally X/GPD G1 hardware 2026-08-30

The external transition initially selected the Samsung TV's native
`3840x2160@60` physical mode while Gamescope/Xwayland later reported the requested
`1920x1080@60` render resolution. The UI and diagnostics should label render and
physical output resolutions separately, and should verify which one a mode
selection is intended to control.

### EGB-026 - Prefer active runtime configuration in remote snapshots

Status: Implemented after hardware capture 2026-08-30

The first after-test snapshot reported stale `HDMI-A-2` and `1002:7480` values
from the legacy state directory even though the active versioned runtime and live
Gamescope process had returned to `*,eDP-1`. Snapshot collection now reads the
active runtime first and uses legacy state only when the runtime file is absent.
A regression test locks that precedence.

### EGB-027 - Report total Game Mode restart time

Status: Implemented after hardware capture 2026-08-30; hardware revalidation pending

The transition record reported readiness polling times of 0.017 seconds external
and 0.015 seconds internal, while the durable transition timestamps show the full
operations took about 6.39 and 4.98 seconds. The timer previously started only
after the blocking `systemctl restart` returned. Restart results now expose
`total_elapsed_seconds` covering the systemd call plus readiness verification,
while retaining the narrower readiness timer for diagnosis.

## Completed in the fork, pending hardware verification

- Connected versus active display detection was separated.
- Generic HDMI/DisplayPort connector handling was added.
- `MESA_VK_DEVICE_SELECT` is applied to the Gamescope user's systemd environment.
- Gamescope user/session detection and plugin path handling were improved.
- A small Gamescope argument shim and reversible user-service drop-in replaced the
  unused copied-session integration path.
- Reloads are skipped when the exact desired state is already live.
- Running Steam games block a session reload unless the caller explicitly confirms.
- A durable transition record and bounded new-PID/argument readiness check replace
  the fixed post-restart sleep.
- Unsafe unplug, fan/OD clock, and NVIDIA driver mutation controls fail closed in
  both the UI and backend.
- Missing internal DRM connector IDs now fail closed instead of guessing ID 108.
- Twenty-seven deterministic tests and CI checks are passing locally.
- A Windows SSH harness can deploy with rollback backup, capture before/live/after
  evidence, and redact saved reports without installing Codex on the target.

The primary switching path received its first ROG Ally X plus GPD G1 hardware
pass on 2026-08-30: the plugin loaded without Decky errors, detected the G1 and
TV, switched Gamescope to the RX 7600M XT and external HDMI connector, rendered a
game at a reported steady 60 FPS, and returned to the internal panel. Broader
hardware verification remains open for repeated cycles, failure recovery, audio,
controller navigation, cable/port comparisons, and the issues recorded above.
