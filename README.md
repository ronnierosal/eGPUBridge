# eGPUBridge

![Version](https://img.shields.io/badge/version-0.3.1-blue)
![Decky](https://img.shields.io/badge/Decky-Loader-green)
![SteamOS](https://img.shields.io/badge/SteamOS-3.x-orange)
![License](https://img.shields.io/badge/license-MIT-green)

**Experimental eGPU manager for SteamOS-compatible Game Mode sessions.** It can select an
external GPU/output, control a TV, expose GPU tuning controls, and recover the internal
display from Decky's quick-access menu.

This fork focuses first on AMD handhelds and AMD USB4 eGPUs, especially the ASUS ROG Ally X
+ GPD G1 path. It fixes connected-vs-active display detection, supports non-default HDMI/DP
connector names, and propagates `MESA_VK_DEVICE_SELECT` to the user systemd manager that
launches Gamescope.

## Features

- **SMART Display Switch** — one-tap toggle between internal and external display
- **GPU Tuning** — power cap, fan control, performance level, overclocking (AMD)
- **TV Control** — ADB-based TV power/input control with Wi-Fi auto-start
- **Experimental NVIDIA tools** — DKMS driver install, activate/deactivate, nvidia-smi telemetry
- **Dock Detection** — USB4/Thunderbolt dock status, ASMedia 246x identification
- **Safe Disconnect** — graceful eGPU removal with PCI cleanup
- **Gamepad UI** — fully navigable with Steam Deck gamepad controls
- **Recovery Hotkeys** — hardware button combos for display recovery

## Compatibility and test status

| Device / setup | Status |
|---|---|
| Lenovo Legion Go S + AMD RX 9070 + ASMedia USB4 | Tested by the upstream author |
| ASUS ROG Ally X + GPD G1 | Targeted by this fork; on-device validation still required |
| Other AMD handheld/eGPU combinations | Expected to work through runtime DRM discovery; unverified |
| NVIDIA eGPUs | Experimental and high-risk; not validated by this fork |

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

## Usage

### SMART Button
The main control — toggles between internal display and eGPU-connected external display. Shows current connector name (e.g., "HDMI 1 TV").

### TV Control
- **ON / HDMI / OFF** — control TV power and input via ADB
- **Wi-Fi Auto Start** — automatically switch TV input when eGPU is detected
- **IP Roller** — gamepad-friendly IP address input for TV

### GPU Tuning (AMD)
- **Power Limit** — adjust GPU power cap (D-pad left/right)
- **Performance Level** — AUTO / HIGH / LOW / MANUAL
- **Power Profile** — BOOTUP / 3D_FULL_SCREEN / POWER_SAVING / etc.
- **Manual Clocks** — GPU/VRAM/Voltage sliders (MANUAL mode)

### GPU Tuning (NVIDIA)
- **Power Cap** — via `nvidia-smi -pl`
- **Fan Control** — auto/manual via `nvidia-settings`
- **Performance Level** — GPUPowerMizerMode (auto/high/low)

### NVIDIA Driver Management
- **Install Driver** — DKMS-based nvidia-dkms installation on SteamOS
- **Activate / Deactivate** — module loading, environment variables, gamescope restart
- **Uninstall Driver** — clean removal with DKMS + pacman

### Other
- **Recovery Hotkey** — toggle hardware button combos for display recovery
- **Safe Unplug** — graceful eGPU disconnect
- **Restore Internal** — switch back to internal display
- **Diagnostics** — collect device info, TV health, recent events

## Building from Source

The plugin uses a pre-built frontend — no build step required.

```bash
# The dist/index.js IS the source (no TypeScript compilation)
# Edit dist/index.js directly for UI changes
# Edit main.py for backend changes

# Verify syntax
node -c dist/index.js
python3 -c "import ast; ast.parse(open('main.py').read())"
python3 -m unittest discover -s tests -v
```

## Architecture

```
eGPUBridge/
├── dist/index.js      # Frontend (React via Decky API)
├── src/index.tsx       # Frontend source snapshot (currently differs from dist)
├── main.py             # Backend (Python, Decky Plugin class)
├── package.json        # Decky plugin metadata
├── plugin.json         # Decky plugin config
├── bin/                # Shell scripts (auto-detect, shutdown)
│   ├── egpubridge-auto.sh
│   ├── egpubridge-shutdown.sh
│   ├── gamescope-session-egpubridge
│   └── platform-tools/ # ADB, fastboot
└── LICENSE
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes (edit `dist/index.js` and/or `main.py`)
4. Test on Steam Deck or compatible device
5. Submit a Pull Request

## ROG Ally X + GPD G1 troubleshooting

If the G1 is detected but the TV stays dark:

1. Connect the TV directly to the G1 and select that TV input.
2. Open eGPUBridge diagnostics and confirm the external connector is `connected` and has
   modes. The name may be `HDMI-A-1`, `HDMI-A-2`, `DP-1`, or another DRM connector.
3. Press **SMART switch to TV**. Expect Game Mode to restart for several seconds.
4. If it remains internal, collect `plugin.log`, the current Gamescope command line, and
   `systemctl --user show-environment | grep MESA_VK_DEVICE_SELECT` over SSH.

This fork sets `MESA_VK_DEVICE_SELECT=<AMD vendor:device>` before restarting Gamescope and
unsets it when restoring the internal display. That addresses the regression reported in
upstream issue #2, but hardware confirmation is still needed on the GPD G1.

## License

[MIT](LICENSE) — Copyright (c) 2026 Vova + GPT
