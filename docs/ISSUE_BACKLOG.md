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

Status: Partially implemented; asynchronous Decky RPC handoff and the native
pre-switch confirmation passed external/internal hardware validation

The demo video shows that selecting the external screen restarts the Game Mode
session. This is not a device reboot: the plugin calls
`systemctl --user restart gamescope-session.target`. A restart remains required
when changing Gamescope startup arguments such as `-O` and
`--prefer-vk-device`. This branch now skips an already-satisfied request, blocks
when a Steam game is running, records a durable transition, and replaces the
fixed six-second sleep with bounded new-PID and exact-argument verification.

The native handoff now writes the transition, returns an accepted operation ID,
requests a Decky notification, and schedules the restart in the backend after the
RPC response. The frontend stops polling while Quick Access is closed and reads
the durable transition through normal status refresh after remount. Remaining
work is to add automatic internal-state rollback when a transition cannot be
reconciled after startup. TV-off automation is deliberately skipped during the immediate
handoff so it cannot delay the RPC; a post-transition automation job remains a
follow-up for users who enable that optional setting.

The 2026-08-30 hardware pass confirmed the original RPC issue: the switch
completed and the returning UI worked, but Decky's websocket router logged that
it dropped the successful RPC result because the restart had already disconnected
the calling socket. A later same-day pass proved the scheduled RPC handoff itself:
both durable transitions completed, no websocket drop/error was logged, and the
external/internal totals were about 5.38 and 4.94 seconds. The operator did not see
the notification before restart on either a one-second or three-second window.
The visible native TV-input confirmation is now the authoritative warning, the
unreliable toast dependency was removed, and the efficient one-second RPC handoff
delay was restored.

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

Status: In progress - guarded release enabled for controlled Ally X/GPD G1 hardware validation

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

Current safe foundation:

- `safe_disconnect_readiness` requires exactly one external DRM GPU with a
  validated PCI identity.
- It resolves only the DRM nodes owned by that exact PCI function and reports
  processes holding those nodes using PID, process name, and UID only.
- The internal Gamescope target must be active.
- The Ally X/GPD G1 profile now proves the selected RX 7600M XT, its HDMI-audio
  function, Titan Ridge xHCI controller, and removable Intel `8086:15ef` parent
  bridge before offering readiness.
- It enumerates USB children, external block devices, mounts, swaps, block-device
  clients, G1 sound nodes, active PCM clients, Steam game scopes, and DRM clients.
- Any external storage is conservatively blocked in the first release even when
  it is unmounted. Running games and active HDMI-audio streams are also blocked.
- A 30-second one-time token binds the final operation to the exact GPU, parent
  bridge, and authorized `Tapex Creek` USB4 identity. Conditions are rechecked
  before any mutation.
- The guarded operation locks future Gamescope configuration to the internal GPU,
  syncs filesystems, removes the exact G1 parent PCI bridge, deauthorizes only the
  matched USB4 device, and reports safe-to-unplug only after the G1 disappears and
  the internal display remains active.
- The token-free Decky-root readiness snapshot was collected and reviewed on the
  Ally X/GPD G1 with zero blockers, so guarded release is enabled for a controlled
  first hardware test. The old destructive paths stay disabled permanently.
- The misleading disabled eject control is replaced by a read-only Disconnect
  Check. Both the title-bar icon and Recovery / Safety row show the same visible
  blocker report and explicitly confirm that no hardware was disconnected.

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
- Decky's native Quick Access visibility hook pauses status polling while the
  panel is closed.
- Display switches can return a durable accepted transition before a scheduled
  Gamescope restart. Hardware proved the clean RPC handoff and native TV-input
  confirmation; Decky toast delivery was not reliable and is no longer required.

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

### EGB-028 - Recover safely when sleep or resume changes eGPU availability

Status: In progress - native resume observation hardware-validated for attached and
disconnected G1 states; externally configured absent-device recovery pending

If the Ally sleeps while Gamescope is bound to the G1, the system may wake after
the G1 was powered off or unplugged. External-only output and a stale Vulkan
device preference can otherwise leave the user with a black or failed Game Mode
session. The Gamescope shim now verifies that the configured vendor/device exists
in PCI sysfs before applying eGPU arguments. When it is absent, the new process
starts with `-O *,eDP-1`, clears its Mesa device selector, and drops the external
mode override. Plugin startup then persists that verified internal failback and
clears the user-manager selector.

The plugin now monitors logind's native `PrepareForSleep` signal and retains the
Linux boot-time versus monotonic gap as a fallback. The direct signal covers
sub-second hardware sleep cycles that cannot be distinguished reliably by timing.
A short debounce prevents the native event and timing fallback from performing
duplicate recovery.
On resume it waits up to twenty seconds for the exact configured vendor/device to
re-enumerate. If it returns, the external configuration is left untouched. If it
remains absent, the observer persists internal configuration, clears the user
Mesa selector, re-enables the Ally panel, restarts Gamescope only when needed,
and writes a compact durable resume outcome. The shim remains the final startup
failback if the plugin observer is unavailable.

The first attached-G1 test entered `s2idle` twice but resumed after approximately
four seconds each time. Both resumes coincided with PCIe AER traffic on the G1's
Titan Ridge path, xHCI recovery failure at `0000:09:00.0`, and spurious PCIe PME
interrupts. The Ally USB4 tunnel at `0000:00:03.1` and the G1 xHCI controller at
`0000:09:00.0` were wake-enabled. These initial results motivated the controlled
wake-source isolation summarized below. The original five-second observer
threshold missed the shortest cycles; the timing fallback is now one second and
uses the suspend-aware boot-time clock when available.

Wake-source isolation disabled the Ally USB4 bridge at `0000:00:03.1` and G1 xHCI
controller at `0000:09:00.0` separately and together. The attached system still
resumed immediately in all three cases. SteamOS reported a successful suspend,
approximately 0.137 seconds of hardware sleep, and ACPI wake IRQ 9. With the G1
powered off and disconnected, the Ally remained asleep for approximately 50
seconds until the operator pressed its power button; the wake IRQ then changed to
7. Gamescope remained internal and Decky stayed active. This confirms the attached
G1/USB4 power-delivery or embedded-controller path as the trigger category, while
also showing that the PCI wake-permission toggles are not a valid workaround.

Remaining acceptance criteria:

- Determine whether an Ally/G1 firmware, embedded-controller, or power-delivery
  update can prevent the ACPI wake while the G1 remains attached.
- Keep the visually validated attached-G1 sleep compatibility warning scoped to
  the hardware-validated Ally X plus RX 7600M XT pair; it must not change the
  ineffective kernel wake permissions.
- Only test removing the G1 during sleep after the platform can sustain attached
  sleep; the current immediate ACPI wake prevents that scenario.
- Hardware-validate that slow G1 enumeration is not mistaken for removal.
- Verify the compact resume record for an externally configured absent-device case;
  the internal/no-G1 resume case is hardware-validated.
- Always prefer a working internal display over automatic return to the eGPU;
  switching external again can remain a deliberate user action.

### EGB-029 - Define safe behavior for in-game eGPU removal

Status: Open - safety guard exists; seamless GPU migration requires feasibility
testing and must not be promised

A running Vulkan/DirectX game normally creates queues and memory on one physical
GPU and cannot migrate that live device to the Ally iGPU. Suspending the process
does not recreate its graphics device. Removing the G1 while a game still owns it
can therefore cause device loss, a hang, or a game crash even if the display has
already switched to the internal panel.

The supported workflow must first identify exact processes, Steam scopes, DRM
nodes, child USB devices, and mounted storage using the selected G1 topology.
While any game or non-migratable GPU client owns the G1, Safe Disconnect should
remain blocked and explain why. A future experiment may preserve a game only when
it was already rendering on the iGPU, or through an explicitly game-specific
save/exit/relaunch flow; it must not claim transparent migration.

Acceptance criteria:

- Enumerate users of the exact eGPU card and render nodes, not every DRM process.
- Switch and verify Gamescope on the internal GPU/display before removal.
- Re-check eGPU clients after the session handoff and block while any remain.
- Include mounted storage and USB children in the same readiness result.
- Never expose a force-unplug override as “safe.”
- Test game-specific outcomes separately and record whether the game continued,
  recovered through relaunch, or could not be preserved.

### EGB-030 - Keep deployment staging outside Decky's plugin scan tree

Status: Implemented after native phase-2 deployment 2026-08-30

Although backups were already outside the live plugin directory, deployment
still unpacked its staging directory beside the active runtime. Decky's watcher
attempted to load that directory before `plugin.json` had been extracted and
logged repeated missing-manifest tracebacks. Staging now occurs under the external
backup root, is cleaned on failure, and is atomically moved into the live plugin
directory only after extraction completes. A harness regression test locks the
staging location.

### EGB-031 - Identify the GPD G1 clearly and warn before the Ally panel goes dark

Status: Implemented and visually validated on ROG Ally X/GPD G1

The validated UI described the connected device as `ASMedia 246x AMD (MESA25.3)`.
That mixed the USB4 bridge, driver, and Mesa version while hiding the actual GPU.
PCI ID `1002:7480` now resolves to `AMD Radeon RX 7600M XT`, and the dashboard uses
that GPU model instead of a hard-coded bridge label.

The first native-handoff pass also appeared to produce black screens only because
the Samsung TV was still on another input while the Ally panel had correctly been
disabled. All external-switch entry points now show a native confirmation telling
the operator to select the G1's HDMI input before the restart is accepted.
The corrected model label, confirmation, external transition, and return to the
Ally all passed the follow-up hardware test.

### EGB-032 - Cache stable platform metadata during dashboard polling

Status: Implemented and hardware-validated on Ally X/GPD G1 2026-08-30

While the Quick Access panel is visible, its five-second status refresh runs
`pacman -Q mesa` every time even though the installed Mesa package cannot normally
change during a gaming session. The live plugin log showed this command repeating
throughout the attached-G1 test. Cache stable package metadata for a bounded period
or plugin lifetime, invalidate it after relevant maintenance actions, and keep live
GPU/link/display state on the normal refresh cadence. Add a regression test proving
repeated status calls do not repeatedly spawn the package manager.

Mesa package metadata is now cached for five minutes while live GPU, link, sensor,
and display state retains the normal dashboard refresh cadence. The regression
suite proves repeated reads use the cache and a later read refreshes after expiry.
Live validation kept the native panel open while `last_status.json` continued to
update on the normal cadence. From plugin startup through more than two minutes of
polling, the log contained exactly one `pacman -Q mesa` invocation. The scoped
sleep-compatibility warning was also visually confirmed on the attached G1.

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
- Forty-five deterministic tests and CI checks are passing locally.
- A Windows SSH harness can deploy with rollback backup, capture before/live/after
  evidence, and redact saved reports without installing Codex on the target.

The primary switching path received its first ROG Ally X plus GPD G1 hardware
pass on 2026-08-30: the plugin loaded without Decky errors, detected the G1 and
TV, switched Gamescope to the RX 7600M XT and external HDMI connector, rendered a
game at a reported steady 60 FPS, and returned to the internal panel. Broader
hardware verification remains open for repeated cycles, failure recovery, audio,
controller navigation, cable/port comparisons, and the issues recorded above.
