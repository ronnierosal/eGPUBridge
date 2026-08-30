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

An attached-G1 suspend test later entered `s2idle` at 13:53:56 and 13:54:11, then
resumed about four seconds after each attempt without operator input. The resume
path reported `BadTLP`, non-fatal `ACSViol`, failed xHCI recovery at
`0000:09:00.0`, and spurious PCIe PME interrupts. The Ally USB4 tunnel
`0000:00:03.1` and G1 Titan Ridge xHCI controller `0000:09:00.0` were both
wake-enabled. This identifies the USB4 path as the leading area for controlled
wake-source isolation, but the initiating device is not yet proven. It also
exposed and led to a fix for the resume observer's former five-second threshold.

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
- Re-run after EGB-023 through EGB-027 improvements are deployed.

Conclusion: the fork's primary Ally X/GPD G1 switching path passed its first live
test. It is ready for focused follow-up testing, not yet for a claim of complete
hardware validation or a broad upstream release.
