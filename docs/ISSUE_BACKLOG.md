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

Status: Implemented in `codex/safe-switching-foundation`; hardware validation pending

The backend now installs a user-systemd environment drop-in that places the small
`bin/gamescope` argument shim ahead of the stock executable. It refuses to switch
if the integration cannot be installed or the user service is unavailable, then
verifies the new live Gamescope command line before disabling the internal panel.

Relevant code:

- [`main.py`](../main.py#L3133)
- [`bin/gamescope-session-egpubridge`](../bin/gamescope-session-egpubridge)

Acceptance criteria:

- Preflight identifies the live Gamescope PID and command line.
- Switching is refused if the requested configuration cannot be consumed.
- Post-start verification confirms the selected GPU, connector, and mode.
- Integration does not overwrite the complete SteamOS-owned session script.

### EGB-002 - Make the Game Mode reload transactional and event-driven

Status: Partially implemented; hardware validation and asynchronous RPC handoff pending

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

Status: Open

Diagnostic reports currently include TV IP/MAC configuration and broad journal
content. Redact local identifiers by default and make inclusion explicit.

Relevant code: [`main.py`](../main.py#L4495)

### EGB-013 - Remove runtime monkey-patching and split `main.py`

Status: Open

`main.py` is over 6,800 lines and replaces `Plugin` methods later through runtime
assignments. This makes it easy to edit an implementation that is no longer the
authoritative path. Split display, hardware, diagnostics, tuning, TV, and driver
operations into modules and define each RPC once.

Relevant code: [`main.py`](../main.py#L4835)

### EGB-014 - Make the frontend reproducible

Status: Open

`src/index.tsx` does not reproduce `dist/index.js`, and the repository has no
source-to-dist verification. Establish a deterministic build and fail CI when
generated output differs, or explicitly declare one canonical source.

### EGB-015 - Replace the copied full Gamescope session script

Status: Implemented with a small argument shim and user-systemd drop-in; hardware validation pending

The bundled wrapper is a complete distribution session script and can drift from
SteamOS. It also contains unrelated low-disk cleanup logic. Replace it with the
smallest supported integration layer or environment/drop-in mechanism.

Relevant code: [`bin/gamescope-session-egpubridge`](../bin/gamescope-session-egpubridge)

## P3 - verification and release hygiene

### EGB-016 - Expand deterministic tests

Status: In progress - deterministic coverage expanded from 7 to 19 tests

Add tests for exact device selection, topology-safe disconnect, transition-state
recovery, reload idempotency, connector detection failures, tuning bounds,
partial-write failures, redaction, and packaging.

### EGB-017 - Improve release provenance

Status: Open

Publish once per tag, verify tag/version consistency, add checksums, and document
the source/version of bundled Android platform tools.

### EGB-018 - Modernize the frontend with Decky UI and Decky API

Status: Deferred until the P0/P1 switching, recovery, and hardware-safety work is fixed and validated

The frontend uses some Decky components, but it also contains hundreds of inline
style declarations, multiple embedded `<style>` blocks, extensive `!important`
overrides, custom focus behavior, and hand-built versions of standard controls.
After the major correctness and safety issues are resolved, migrate the frontend
to the current Decky plugin template and use components imported directly from
`@decky/ui` plus RPC helpers from `@decky/api`.

Recommended replacements include:

- `ButtonItem` or `DialogButton` for custom action-button wrappers.
- `ToggleField` for hand-built toggle rows.
- `Dropdown` for performance and GPU-profile selectors.
- `SliderField` for tuning ranges.
- `Field`, `PanelSection`, and `PanelSectionRow` for standard layout and status rows.
- Typed `callable()` functions and `definePlugin()` from `@decky/api` instead of
  runtime global discovery and direct legacy `callPluginMethod` wrappers.

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

Relevant code: [`src/index.tsx`](../src/index.tsx)

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
- Nineteen deterministic tests and CI checks are passing locally.

These changes still require a ROG Ally X plus GPD G1 hardware run before being
considered verified.
