# Cross-platform feature parity

Parity contract version: **1**

This file is intentionally mirrored in both repositories:

- [eGPUBridge for SteamOS/Decky](https://github.com/ronnierosal/eGPUBridge)
- [eGPUBridge for Windows](https://github.com/ronnierosal/eGPUBridge-Windows)

Update both copies when a shared feature, state name, safety rule, or parity
decision changes. The implementations remain independent and use supported
native APIs on each operating system.

## Product rule

The applications should feel like two builds of the same product. They should use
the same user-facing feature names, state model, safety expectations, diagnostic
language, and broad workflow where that makes sense. They should not force the
same low-level implementation.

- SteamOS uses Decky, DRM/sysfs discovery, Gamescope, and user systemd services.
- Windows uses WPF, DisplayConfig, Configuration Manager/device notifications,
  and Windows-managed display topologies.

A feature can reach parity even when the platform mechanics are different.

## Shared vocabulary

Display modes:

- **Internal** — handheld panel is the intended active display.
- **External** — selected TV/monitor is the intended active display.
- **Extend** — internal and external displays form one extended desktop.
- **Duplicate** — internal and external displays mirror one another.
- **Unknown** — the application cannot prove the current mode.

Transition states:

- **Idle**
- **Preflight**
- **Blocked**
- **Applying**
- **Waiting**
- **Verifying**
- **Succeeded**
- **Rolling back**
- **Failed**

Every display transition should eventually expose the same conceptual result,
even if the language-specific model differs:

- operation ID;
- requested, previous, and final display mode;
- exact adapter and display identity when known;
- start time and duration;
- whether a Game Mode/session handoff was required;
- verification evidence;
- warnings and a stable error code;
- rollback outcome when recovery was necessary.

## Feature matrix

Status meanings:

- **Available*** — implemented, but the target Ally X/GPD G1 hardware pass is pending.
- **Partial** — useful foundation exists but does not meet the shared acceptance criteria.
- **Planned** — not implemented.
- **Disabled** — intentionally unavailable until the safety criteria are met.
- **Platform** — intentionally specific to that operating system.

| ID | Shared capability | SteamOS/Decky | Windows | Parity decision |
|---|---|---:|---:|---|
| EGB-C01 | Display and adapter inventory | Available* | Available* | Show internal/external classification and stable native identifiers. |
| EGB-C02 | Current display-mode detection | Available* | Available* | Never equate “connected” with “active.” Use **Unknown** when proof is incomplete. |
| EGB-C03 | Manual Internal/External switching | Available* | Available* | Preflight, confirm, apply, verify, and preserve a recovery path. |
| EGB-C04 | Extend and Duplicate modes | Planned | Available* | Expose only where the platform supports a verified implementation. |
| EGB-C05 | Idempotent switching | Available* | Planned | Skip an operation when the requested exact state is already live. |
| EGB-C06 | Running-game guard | Available* | Planned | Block disruptive switching unless the user explicitly confirms. |
| EGB-C07 | Verified transition and rollback | Partial | Partial | Replace fixed delays with bounded readiness checks and restore the prior state on failure. |
| EGB-C08 | Exact GPD G1 identity | Planned | Planned | Bind behavior to PCI/device/topology identity, never “first secondary GPU.” |
| EGB-C09 | Hot-plug arrival/removal events | Partial | Planned | Record device events; do not auto-switch until manual flow is reliable. |
| EGB-C10 | Structured troubleshooting logs | Available* | Available* | Use the shared event names below and retain platform-native evidence. |
| EGB-C11 | Redacted support export | Available* | Planned | Redact local user, host, network, and device-serial identifiers by default. |
| EGB-C12 | Remote supervised testing | Available* | Planned | Permit another computer to capture logs without installing Codex on the handheld. |
| EGB-C13 | Saved per-setup profiles | Planned | Planned | Key profiles to exact adapter plus display identity and verify after applying. |
| EGB-C14 | Opt-in automatic switching | Partial | Planned | Require a reliable manual flow, explicit enablement, debounce, and rollback first. |
| EGB-C15 | Safe physical disconnect | Disabled | Disabled | Do not claim safety until displays, GPU users, child devices, storage, and mounts are proven idle. |
| EGB-C16 | TV power/input integration | Available* | Planned | Share the workflow; use platform-appropriate ADB, Wake-on-LAN, or CEC integration. |
| EGB-P01 | Gamescope/session handoff | Platform | Not applicable | SteamOS-only implementation detail. |
| EGB-P02 | Windows tray and saved topology modes | Not applicable | Available* | Windows-only shell and DisplayConfig behavior. |
| EGB-P03 | GPU power/performance controls | Partial | Planned | Optional enhancement, not core parity; remain conservative and device-bounded. |

## Shared safety contract

Both builds must follow these rules:

1. Display switching and hardware mutation are separate capabilities.
2. A connected display or secondary adapter is not automatically the GPD G1.
3. Hardware-specific actions require an exact, persisted identity and live
   topology verification.
4. Driver installation/removal is not an in-app operation.
5. Fan, clock, voltage, and PCI removal controls stay disabled until bounds,
   rollback, and fail-safe behavior are tested on the exact device.
6. A disruptive transition checks for running games and provides an explicit
   warning or block.
7. Success means the requested final state was observed, not merely that the
   operating-system API accepted the request.
8. Failure preserves or restores access to the handheld's internal panel.
9. Logs and support reports redact local identifiers by default.
10. “Safe unplug” remains unavailable until storage and child-device dependencies
    are included in the proof.

## Shared diagnostic events

Implementations should use these event names where applicable:

- `display.snapshot`
- `display.transition.requested`
- `display.transition.blocked`
- `display.transition.applied`
- `display.transition.verified`
- `display.transition.rollback.started`
- `display.transition.rollback.completed`
- `display.transition.failed`
- `device.arrived`
- `device.removed`
- `support.report.created`

Platform-specific fields are allowed. Shared fields should keep the same meaning.

## Build and release parity

Both repositories should:

- use a pinned, reproducible toolchain;
- build and test on pushes and pull requests;
- keep hardware-independent regression tests in CI;
- verify packaged contents before release;
- publish one release per matching version tag;
- attach a SHA-256 checksum;
- document whether artifacts are signed;
- block public-release claims until the Ally X/GPD G1 hardware checklist passes.

Versions and release dates remain independent because the platform
implementations mature at different rates.

## Recommended implementation order

1. Validate current inventory and manual display switching on the real hardware.
2. Add exact GPD G1 and TV identity.
3. Implement the shared transition result and diagnostic events.
4. Add idempotency, running-game protection, readiness verification, and rollback.
5. Add redacted support export and remote capture to Windows.
6. Add saved profiles and hot-plug event logging.
7. Consider opt-in automation and TV integration.
8. Revisit safe disconnect and tuning only after their safety prerequisites exist.

