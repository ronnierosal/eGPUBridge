# eGPUBridge fork integration and upstream plan

## Why changes should be staged

The validated fork is currently dozens of commits and more than ten thousand
changed lines ahead of upstream. It combines build modernization, safety fixes,
remote diagnostics, native Decky work, and GPD G1-specific behavior. Sending that
history as one upstream pull request would make review and regression isolation
unnecessarily difficult.

Do not open a broad upstream pull request directly from the active development
branches. First integrate and validate the fork, then reconstruct small branches
from upstream `main` for each independently reviewable capability.

## Active branch ownership

- `codex/core-reliability`: backend safety, hardware identity, resume/removal,
  remote testing, release gates, and documentation.
- `codex/decky-native-controls`: native Decky UI controls and frontend styling.

The native-controls branch should avoid backend switching semantics. The
core-reliability branch should avoid `src/index.tsx` and `dist/index.js` except for
an integration conflict that is reviewed after both branches are complete.

## Fork integration sequence

1. Finish and verify each active branch independently.
2. Deploy the core-reliability branch to the Ally X and run the hardware gates
   below.
3. Merge the native-controls branch into a temporary fork integration branch.
4. Resolve generated frontend output only by rebuilding from `src/index.tsx`.
5. Re-run the complete CI and hardware smoke checklist.
6. Merge the reviewed integration branch into the fork's `main`.
7. Tag a prerelease only after the package version, tag, checksum, and artifact
   metadata agree. The likely next line is `0.4.0-beta.1`; do not bump it merely
   for development deployments.

## Hardware release gates

- External and internal switching both complete and return to Decky.
- Repeating the already-active target skips the Game Mode restart.
- A running Steam game blocks disruptive switching and G1 release.
- `egpu_identity.json` is created only after a verified G1 transition, contains
  no raw USB4 unique ID, and survives a deployment.
- Disconnect Check, Release G1, physical unplug, and reconnect pass with the Ally
  display remaining usable.
- Hot-plug status updates without leaving the plugin.
- TV audio routing and controller navigation are checked.
- Resume with no configured external GPU remains internal and usable.
- A controlled failed external transition proves automatic internal rollback
  before rollback is described as hardware-validated.

## Proposed upstream pull-request slices

### 1. Reproducible native build and API contract

Include the locked TypeScript/Rollup build, typed Decky RPC registry, generated
bundle verification, package checks, and CI. Avoid hardware behavior changes.

### 2. Safe Gamescope switching foundation

Include the argument shim, user-systemd drop-in, exact desired-state verification,
idempotency, running-game guard, asynchronous handoff, durable transitions, and
internal rollback. Keep the patch focused on display/session behavior.

### 3. Privacy-safe diagnostics and remote testing

Include default redaction, bounded logs, the Windows SSH harness, transactional
deployment, runtime discovery, and backup/staging isolation.

### 4. Ally X and GPD G1 reliability profile

Include the exact G1 topology binding, sleep compatibility warning, resume
observer, guarded live release, hot-plug events, and hardware evidence. Present
this as a device-scoped capability rather than a promise for every enclosure.

Each upstream slice should be rebuilt from current upstream `main`, carry only the
tests and documentation needed for that capability, and mention its dependency on
earlier accepted slices. Do not merge or publish from an unreviewed reconstruction.
