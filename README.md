# eGPUBridge

![Version](https://img.shields.io/badge/version-0.3.1-blue)
![Decky](https://img.shields.io/badge/Decky-Loader-green)
![SteamOS](https://img.shields.io/badge/SteamOS-3.x-orange)
![License](https://img.shields.io/badge/license-MIT-green)

**Experimental eGPU manager for SteamOS-compatible Game Mode sessions.** It can select an
external GPU/output, control a TV, expose limited GPU telemetry and power controls, and
recover the internal display from Decky's quick-access menu.

This fork focuses first on AMD handhelds and AMD USB4 eGPUs, especially the ASUS ROG Ally X
+ GPD G1 path. It fixes connected-vs-active display detection, supports non-default HDMI/DP
connector names, and propagates `MESA_VK_DEVICE_SELECT` to the user systemd manager that
launches Gamescope.

## Related project and feature parity

- [eGPUBridge for Windows](https://github.com/ronnierosal/eGPUBridge-Windows)
- [Shared cross-platform feature contract](docs/CROSS_PLATFORM_PARITY.md)

The projects share product behavior, terminology, safety rules, diagnostics, and
feature planning. Their native display and session implementations remain
platform-specific.

## Features

- **SMART Display Switch** — one-tap toggle between internal and external display
- **Conservative GPU Controls** — telemetry, power cap, and safe performance levels (AMD)
- **TV Control** — ADB-based TV power/input control with Wi-Fi auto-start
- **NVIDIA telemetry** — driver mutation is intentionally disabled in this AMD-focused fork
- **Dock Detection** — USB4/Thunderbolt dock status, ASMedia 246x identification
- **Fail-closed unplug control** — PCI removal stays disabled until topology and storage checks exist
- **Gamepad UI** — fully navigable with Steam Deck gamepad controls
- **Recovery Hotkeys** — hardware button combos for display recovery

## Compatibility and test status

| Device / setup | Status |
|---|---|
| Lenovo Legion Go S + AMD RX 9070 + ASMedia USB4 | Tested by the upstream author |
| ASUS ROG Ally X + GPD G1 | Initial on-device external/internal switching validation passed; extended reliability testing remains |
| Other AMD handheld/eGPU combinations | Expected to work through runtime DRM discovery; unverified |
| NVIDIA eGPUs | Telemetry only; driver and PCI mutation are disabled |

The original repository's broader “full support” claims were not backed by a device test
matrix. Keep SSH access available while testing any display-session change.

## Installation

This project is not currently published in the Decky Plugin Store. Install it manually:

1. Download a ZIP from this repository's [Releases](../../releases), or clone the source.
2. Copy the complete project folder to `~/homebrew/plugins/eGPUBridge/`.
3. Restart Decky with `sudo systemctl restart plugin_loader`.

> **Note:** Plugin requires `root` flag — Decky will prompt for sudo access.

For development, copy the folder under the actual Decky user's home directory. The Python
backend now discovers its own plugin directory, and the Gamescope helper discovers the
active Gamescope user instead of assuming that user is always named `deck`.

On the first display switch, the plugin installs a small user-systemd environment drop-in
for `gamescope-session.service`. This puts the plugin's argument shim ahead of the stock
`gamescope` binary. It does **not** replace `/usr/lib/steamos/gamescope-session`. If this
preflight cannot be installed or the unit is not present, switching fails without turning
off the internal display.

## Usage

### SMART Button
The main control — toggles between internal display and eGPU-connected external display. Shows current connector name (e.g., "HDMI 1 TV").

### TV Control
- **ON / HDMI / OFF** — control TV power and input via ADB
- **Wi-Fi Auto Start** — automatically switch TV input when eGPU is detected
- **IP Roller** — gamepad-friendly IP address input for TV

### GPU Tuning (AMD)
- **Power Limit** — adjust GPU power cap (D-pad left/right)
- **Performance Level** — AUTO / HIGH / LOW
- **Fan and manual clock/voltage writes** — disabled until device-specific bounds, rollback,
  and a watchdog are implemented

### NVIDIA support

NVIDIA driver installation, removal, activation, and deactivation are hidden in the UI and
rejected by the backend. Installing OS drivers from a root Decky RPC is outside this fork's
safe scope.

### Other
- **Recovery Hotkey** — toggle hardware button combos for display recovery
- **Safe Unplug** — currently disabled; disconnect the G1 only after restoring internal mode
- **Restore Internal** — switch back to internal display
- **Diagnostics** — collect device info, TV health, recent events

## Building from Source

The frontend is built from TypeScript with the official Decky Rollup preset. Use
Node.js 20+ and pnpm 9:

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
pnpm check:frontend-contract

# Verify backend and generated output
node --check dist/index.js
python3 -m py_compile main.py
python3 -m unittest discover -s tests -v
```

`src/index.tsx` and `src/backend.ts` are authoritative. Commit the generated
`dist/index.js` with frontend changes; CI rebuilds it and fails if the checked-in
bundle has drifted. The large legacy UI remains temporarily
`@ts-nocheck`, while the native Decky RPC registry and build configuration are
type-checked normally.

## Architecture

```
eGPUBridge/
├── dist/index.js       # Generated Decky frontend bundle
├── src/index.tsx       # Authoritative frontend source
├── src/backend.ts      # Typed @decky/api RPC registry
├── main.py             # Backend (Python, Decky Plugin class)
├── package.json        # Decky plugin metadata
├── plugin.json         # Decky plugin config
├── bin/                # Runtime helpers and bundled Android tools
│   ├── gamescope                 # Small argument-injection shim
│   └── platform-tools/ # ADB, fastboot
├── scripts/            # Build checks and Windows SSH test harness
└── docs/               # Issue backlog and remote-test instructions
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make frontend changes under `src/` or backend changes in `main.py`
4. Run the build, contract check, and regression tests
5. Test on Steam Deck or compatible device
6. Submit a Pull Request

Remote Ally deployment and log capture are documented in
[`docs/REMOTE_TESTING.md`](docs/REMOTE_TESTING.md). Bundled binary provenance is
recorded in [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md).

## ROG Ally X + GPD G1 troubleshooting

If the G1 is detected but the TV stays dark:

1. Connect the TV directly to the G1 and select that TV input.
2. Open eGPUBridge diagnostics and confirm the external connector is `connected` and has
   modes. The name may be `HDMI-A-1`, `HDMI-A-2`, `DP-1`, or another DRM connector.
3. Close any running game, then press **SMART switch to TV**. The plugin blocks the reload
   if it detects a Steam game scope. Expect Game Mode to restart for several seconds only
   when the requested output/GPU/mode differs from the live Gamescope process.
4. If it remains internal, collect `plugin.log`, the current Gamescope command line, and
   `systemctl --user show-environment | grep MESA_VK_DEVICE_SELECT` over SSH. Also collect
   `~/.config/systemd/user/gamescope-session.service.d/50-egpubridge.conf`.

This fork sets `MESA_VK_DEVICE_SELECT=<AMD vendor:device>` before restarting Gamescope and
unsets it when restoring the internal display. It records the transition, waits for a new
Gamescope PID with the exact requested arguments, and keeps the internal panel enabled if
verification fails. The combined reliability and native-Decky stage 2 build completed a
supervised GPD G1 external/internal round trip on a ROG Ally X. Repeated cycles, controlled
rollback, cable/port comparisons, audio, HDR, and running-game protection still require
hardware validation.

## License

[MIT](LICENSE) — Copyright (c) 2026 Vova + GPT
