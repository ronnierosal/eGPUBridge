# HDM Reference Handoff

This document records only facts learned from eGPUBridge for future
`handheld-dock-mode-steamos` and `handheld-dock-mode-windows` work. It does not
define or begin HDM architecture.

## Proven on the tested SteamOS hardware

- The ROG Ally X detects the GPD G1 reliably after a clean enumeration.
- The RX 7600M XT can be identified exactly as PCI vendor/device `1002:7480` and
  tied to the validated Titan Ridge/USB4 topology.
- A connected TV can be discovered through generic DRM HDMI/DP enumeration and
  its EDID/modes inspected before switching.
- Gamescope can switch from the Ally panel to the G1-connected TV and back.
- Final measured transitions were 5.9 seconds to the TV and 4.615 seconds back to
  the Ally; other validated passes were also in the approximate 4–8 second range.
- An already-internal restore can be idempotent: no Gamescope restart, PID change,
  screen flicker, or display transition is required.
- Running Steam games can be detected through user systemd scopes. The corrected
  hardware pass recognized `app-steam-app2909400-43899.scope`, visibly blocked the
  switch, preserved the game, kept Gamescope PID `38083`, and left the TV active.
- Native Decky confirmation and blocked-action dialogs can be surfaced before a
  disruptive display action.
- eGPU connection state can refresh automatically while the plugin remains open.
- PCIe/AER and xHCI telemetry can be collected and summarized remotely over SSH
  without installing Codex on the handheld.

## Probable but not proven

- The GPD G1 may render to the Ally internal panel. Higher frame rates and G1 fan
  activity were observed while the panel was visible, but no live Gamescope GPU
  selection or per-process Vulkan capture proved the rendering path. EGB-035
  remains open.

## Not safe or supported

- Physically unplugging the G1 while the Ally is running.
- Migrating a running game from the Ally iGPU to the G1 eGPU.
- Migrating a running game from the G1 eGPU to the Ally iGPU.
- Assuming an active GPU workload can survive a Gamescope restart.
- Proceeding when eGPU identity, connector readiness, or running-game state is
  unknown.

## Reusable engineering lessons

- Separate display target, render GPU, and physical connection state. A connected
  connector is not necessarily the active display or selected renderer.
- Use exact hardware identity and live state, not DRM card numbers or a generic
  “first external GPU” rule.
- Treat Steam scope formats as an evolving interface and fail closed on unknown
  current-style game scopes.
- Compare desired Gamescope arguments with the live process before restarting.
- Persist transition intent, return control to the UI, and verify the new PID and
  exact arguments after restart.
- Preserve remote, redacted before/live/after evidence for hardware-dependent
  changes.
- The source repository is MIT licensed. Reuse must preserve its copyright and
  permission notice in substantial copied portions.

## Future HDM research experiment

Investigate this Switch-like sequence separately in HDM:

1. A game is already running on the Ally iGPU and internal panel.
2. The G1 and TV become available.
3. Keep the existing game rendering on the iGPU.
4. If the platform permits it, present or move the existing session to the TV
   without migrating the game's GPU or restarting Gamescope.
5. After the game exits, allow newly launched games to select the eGPU.

This experiment was not implemented or validated in eGPUBridge. It must begin as
a read-only capability investigation in the new HDM project, with explicit proof
that the existing session can move without GPU migration or game termination.
