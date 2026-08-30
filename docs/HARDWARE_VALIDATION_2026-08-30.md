# ROG Ally X and GPD G1 hardware validation - 2026-08-30

## Scope

This was the first supervised hardware pass of fork version 0.3.1 on a ROG Ally X
running SteamOS with a GPD G1 (AMD Radeon RX 7600M XT, PCI ID `1002:7480`) and a
Samsung TV connected to the G1 HDMI output. Codex ran on a separate Windows
computer and collected redacted evidence over SSH; Codex was not installed on the
Ally.

Local capture: `test-results/20260830-123448/` (intentionally ignored by Git).

Native-handoff follow-up capture: `test-results/20260830-132108/`
(intentionally ignored by Git).

Native confirmation follow-up capture: `test-results/20260830-133757/`
(intentionally ignored by Git).

Combined reliability/native-stage-2 round-trip capture:
`test-results/20260830-163425/`, with final state snapshot in
`test-results/20260830-163744/` (intentionally ignored by Git).

## Result

Primary display switching passed:

- Decky loaded eGPUBridge 0.3.1 without current plugin errors.
- The plugin detected the G1, selected `card1-HDMI-A-1`, and identified the TV.
- External transition completed with Gamescope using
  `-O HDMI-A-1 --prefer-vk-device 1002:7480`.
- The RX 7600M XT reported a `16 GT/s` x8 PCIe link through sysfs/lspci.
- The operator observed stable TV output, a reported 60 FPS in Final Fantasy VII
  Rebirth, and increased G1 fan activity.
- Internal transition completed with Gamescope using `-O *,eDP-1` and no eGPU
  preference.
- The operator confirmed that Gaming Mode returned to the Ally display without a
  visible issue.
- After the G1 was powered off and disconnected, the external PCI device was
  removed and the internal Gamescope session remained running.

Durable transition timestamps measured approximately 6.39 seconds for the
external transition and 4.98 seconds for the internal transition. The old
readiness-only timer incorrectly reported 0.017 and 0.015 seconds because it
started after the blocking systemd restart returned; EGB-027 corrects that
telemetry for future runs.

The later native-handoff pass completed another external/internal round trip on
`card2-HDMI-A-2`. The backend returned accepted transitions before restarting,
Decky logged no dropped successful RPC result, and the durable records completed
in approximately 5.38 seconds external and 4.94 seconds internal. The operator did
not see the requested Decky notification. The TV initially appeared black because
it was on the wrong input, while the Ally panel had intentionally been disabled;
selecting the G1 input exposed the already-running external session. EGB-002 and
EGB-031 track the longer notice window and native TV-input confirmation added from
this observation.

The next follow-up visually confirmed the corrected `RX 7600M XT · Mesa 25.3`
dashboard label and native TV-input confirmation. External output activated and
the operator returned to the Ally; the internal durable transition completed in
approximately 4.97 seconds with no Decky websocket error. The Decky toast remained
invisible even with a three-second delay. Because the modal provides the warning
before any mutation and passed on hardware, the toast dependency was removed and
the one-second asynchronous RPC delay restored.

The combined `codex/core-native-stage2` build then completed an external/internal
round trip after the deployment harness was hardened against Windows CRLF shell
scripts. The external transition selected `HDMI-A-1`, bound Gamescope to
`1002:7480`, persisted the exact G1 identity, and completed in approximately 5.93
seconds. The operator confirmed TV output. The return transition selected
`*,eDP-1`, removed the eGPU preference, and completed in approximately 4.44
seconds; the operator confirmed the Ally panel returned. Gamescope remained
active and the G1 remained present with the AMDGPU driver attached.

## Findings requiring follow-up

The successful user-visible result does not make the full hardware path clean.
The live journal contained:

- 84 correctable PCIe Bus Error records.
- 78 `BadDLLP` and 7 `BadTLP` records.
- 10 non-fatal uncorrectable `ACSViol` records.
- 10 xHCI recovery failures and 10 parent-device recovery failures.
- 59 failed AMDGPU SMU metric exports during powered-off removal.
- 9 `MES failed to respond to msg=REMOVE_QUEUE` cleanup failures.
- No captured GPU reset or device-lost event.

The PCIe AER events affected the G1 USB4/Thunderbolt topology while output and
rendering continued. This should first be compared using a reseated cable, a
known-certified USB4 cable, and the Ally's other USB4 port before considering any
kernel workaround.

The combined-build round trip reproduced the same link warnings on the external
and internal sides of the handoff: correctable `BadDLLP` reports on the Intel
`15ef` bridge, non-fatal `ACSViol`, and failed xHCI recovery for `0000:09:00.0`.
Both user-visible transitions still completed. This confirms EGB-023 remains an
independent USB4/PCIe link-health investigation rather than a transition failure.

An attached-G1 suspend test later entered `s2idle` at 13:53:56 and 13:54:11, then
resumed about four seconds after each attempt without operator input. The resume
path reported `BadTLP`, non-fatal `ACSViol`, failed xHCI recovery at
`0000:09:00.0`, and spurious PCIe PME interrupts. The Ally USB4 tunnel
`0000:00:03.1` and G1 Titan Ridge xHCI controller `0000:09:00.0` were both
wake-enabled. This identifies the USB4 path as the leading area for controlled
wake-source isolation; at that stage the initiating category was not yet proven.
It also exposed and led to a fix for the resume observer's former five-second
threshold.

Follow-up isolation disabled the G1 xHCI wake permission, the Ally USB4 bridge
wake permission, and then both simultaneously. All three attached-G1 attempts
still resumed immediately. Suspend statistics showed no failures, only about
0.137 seconds of hardware sleep, and ACPI wake IRQ 9. After switching Gamescope
to `*,eDP-1`, powering off and disconnecting the G1 allowed approximately 50
seconds of hardware sleep until the operator pressed the Ally power button; wake
IRQ then changed to 7. Decky remained active, Gamescope stayed internal, and the
resume observer recorded `resume_no_external_configuration`. The attached
G1/USB4 power-delivery or embedded-controller path is therefore the confirmed
trigger category, while the two tested PCI wake toggles are ineffective.

The first deployment of the native logind monitor passed a disconnected sleep
cycle lasting about 67 seconds in hardware. It recorded `suspend_preparing`, kept
Decky active and Gamescope internal, and performed recovery once. The clock-gap
fallback won a resume-time scheduling race before the direct signal was processed,
so a 0.75-second fallback grace period was added. A second disconnected cycle then
recorded `login1_prepare_for_sleep` first and ignored the timing fallback as a
duplicate. The final attached-G1 cycle also used the native signal without needing
the fallback: the full signal interval was 3.379 seconds, hardware sleep was only
0.137 seconds, wake IRQ was ACPI 9, and the G1 remained present. Decky stayed active
and Gamescope/configuration remained on the Ally's internal display throughout.

Keeping the native dashboard open during these tests also exposed `pacman -Q mesa`
running every five seconds. EGB-032 tracks caching this stable package metadata
without slowing live GPU, link, or display updates.

The cache and compatibility-warning deployment then passed live validation. The
dashboard visibly showed the amber sleep warning for the detected G1. During more
than two minutes with the panel open, `last_status.json` kept refreshing while the
plugin log contained exactly one `pacman -Q mesa` invocation at startup. This
confirms the five-minute cache removed package-manager polling without freezing
live dashboard state.

Read-only topology work for safe live unplug identified one exact G1 PCI subtree
under the Ally root port `0000:00:03.1`. The removable enclosure root is Intel
Titan Ridge bridge `0000:04:00.0` (`8086:15ef`). Its children include RX 7600M XT
`0000:08:00.0`, HDMI/DP audio `0000:08:00.1`, and Titan Ridge xHCI
`0000:09:00.0`; the authorized USB4 device is the sole non-host `0-2` device,
reported as Intel `Tapex Creek`. No block devices were below that subtree during
inspection. G1 sound nodes belong to card 2; WirePlumber holds its control node,
but no PCM playback node was open. SteamOS exposes card and render device nodes
for the G1 while the optional DRM control node is absent from `/dev/dri`, which is
now handled without weakening the required card/render identity checks.

The deployed Decky-root report then proved the same topology with zero blockers:
the Ally display was active, no Steam games or DRM clients were present, no PCM
audio stream was open, no block devices were below the G1, and the only sound
client was WirePlumber monitoring `controlC2`. The token-free report also matched
the exact `Tapex Creek` identity and contained no unexpected PCI endpoints. This
evidence enabled the guarded release path for a controlled first removal test.

The guarded release then passed its first hardware test. eGPUBridge completed a
fresh readiness recheck, removed the exact G1 enclosure root, deauthorized the
matched USB4 device, verified that the Ally remained on its internal display, and
reported `Safe to unplug`. The operator unplugged the cable without a visible Ally
or Decky failure. The kernel logged expected AMDGPU/xHCI teardown plus non-fatal
AER recovery noise. Reconnecting the G1 enumerated the same topology and completed
AMDGPU initialization despite PCI BAR allocation warnings and a 256 MiB fallback.
The G1 was usable and detected again.

Later evidence invalidated the initial live-release pass. The previous-boot
journal showed `irq/39-pciehp` blocked in `amdgpu_device_fini_hw` and
`amdgpu_pci_remove` for more than ten minutes. Subsequent G1 power cycles left the
GPU visible on PCI without an attached driver or DRM card, and a restart with the
G1 connected hung at the ROG logo until the Ally was hard-powered off and booted
without the enclosure. A clean post-boot hot-connect then initialized AMDGPU and
restored card 1 at `16 GT/s x8`. Live PCI/USB4 release is therefore quarantined;
Disconnect Check remains read-only and users must shut down before unplugging.

That reconnect exposed a frontend freshness gap: the backend status was current,
but the `Dock / eGPU` summary did not change until the plugin was reopened. EGB-033
tracks the paired automatic refresh and visible manual refresh control added from
this observation.

The EGB-033 deployment subsequently passed its hardware check. With eGPUBridge
kept open, the reconnected G1 appeared automatically within five seconds. The
operator did not leave the page or use the new manual Refresh button.

Power-off/removal began at 12:42:43 and AMDGPU cleanup messages ended at 12:43:11.
The G1 PCI device then disappeared and the Ally remained usable. EGB-003 and
EGB-024 track the safe-unplug and removal-reconciliation work.

The TV initially used a native `3840x2160@60` physical mode while Gamescope's
requested render resolution was `1920x1080@60`. EGB-025 tracks clearer render
versus physical-mode reporting.

The remote after-snapshot initially preferred stale legacy state files over the
active versioned runtime. EGB-026 fixes that diagnostic-only precedence issue.

Decky's websocket router dropped the successful return value from the internal
switch RPC because restarting Gamescope tore down the calling UI socket first.
The UI returned and the transition succeeded, but this live evidence confirms the
remaining asynchronous handoff work in EGB-002.

## Still to validate

- Repeat several external/internal cycles without launching a game during the
  transition.
- Compare both Ally USB4 ports and at least one other certified USB4 cable.
- Verify TV audio routing, controller navigation, HDR, suspend/resume, and Decky
  recovery after each Game Mode restart.
- Verify idempotency: requesting the already-active target must skip the restart.
- Verify running-game protection rather than overriding it during normal use.
- Exercise timeout and rollback behavior in a controlled failure test.
- Re-run after EGB-023 link-health diagnostics are implemented and compare the
  warning rate across cables and both Ally USB4 ports.

Conclusion: the fork's primary Ally X/GPD G1 switching path and the combined
reliability/native-stage-2 build both passed supervised live external/internal
round trips. The fork is ready for focused follow-up testing, not yet for a claim
of complete hardware validation or a broad upstream release.
