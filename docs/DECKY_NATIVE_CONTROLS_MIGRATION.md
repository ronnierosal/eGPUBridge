# Decky native controls migration

EGB-018 is being delivered as small hardware-gated stages. Each stage changes one
isolated UI surface, retains the existing RPC names and arguments, regenerates
`dist/index.js`, and must pass the complete local regression suite before Ally X
deployment.

Do not remove the remaining compatibility CSS or hand-built controls until their
replacement has passed gamepad validation on the ROG Ally X.

## Stage 1 - Debug Info toggle

Scope: replace only the local `Debug Info` switch with Decky's `ToggleField`.
This control changes React display state only. It does not call the backend or
change polling, display configuration, safe-unplug state, or hardware.

### Deploy to the ROG Ally X

From Windows PowerShell in the repository root:

```powershell
# Confirm SSH, Decky, and the active runtime before changing anything.
./scripts/ally-remote-test.ps1 -Action Preflight -HostName <ally-host> -UserName deck -IdentityFile <ssh-key>

# Save a read-only baseline snapshot.
./scripts/ally-remote-test.ps1 -Action Snapshot -HostName <ally-host> -UserName deck -IdentityFile <ssh-key>

# Build, run backend tests, deploy transactionally, and restart Decky.
./scripts/ally-remote-test.ps1 -Action Deploy -HostName <ally-host> -UserName deck -IdentityFile <ssh-key> -ConfirmDeploy -InteractiveSudo
```

The deploy runner stores the replaced runtime under
`/home/deck/homebrew/plugin-backups/eGPUBridge/`, outside Decky's plugin scan
directory.

### Stage 1 gamepad test

1. Open Quick Access, then eGPUBridge, and confirm the dashboard continues to
   refresh while visible.
2. Expand `Other`. Use only the Ally controls to move focus to `Debug Info`.
   Confirm the row uses Decky's normal focus highlight and the toggle is fully
   visible at the Quick Access width.
3. Press A once. Confirm the toggle turns on and the native `Gamescope` and
   `Last result` sections appear below the accordion.
4. Navigate through both new sections, return to `Debug Info`, and press A again.
   Confirm both detail sections disappear and focus remains usable.
5. Close and reopen Quick Access. Confirm the main status immediately catches up,
   polling resumes only while the panel is visible, and there are no duplicate
   focus activations.
6. Run a read-only `Disconnect Check`; confirm it still says no hardware was
   disconnected and presents the same blocker/readiness result as before.
7. If the GPD G1 and TV are connected and the normal preconditions are satisfied,
   perform one supervised external-to-internal display round trip. Confirm the
   native TV-input warning appears before the external switch, both durable
   transitions complete, and the Ally returns to its internal panel before any
   cable removal. Do not launch a game during the transition.
8. Save an after-test snapshot and inspect current Decky/plugin errors:

```powershell
./scripts/ally-remote-test.ps1 -Action Snapshot -HostName <ally-host> -UserName deck -IdentityFile <ssh-key>
```

Record the Ally OS/Decky versions, attached G1/TV state, controller-navigation
result, display round-trip result (or why it was skipped), and snapshot directory
before starting stage 2.
