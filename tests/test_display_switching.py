import unittest
import tempfile
import inspect
import json
import re
import base64
import zlib
import os
from pathlib import Path
from unittest import mock

import main


class RemoteHarnessTests(unittest.TestCase):
    def test_remote_scripts_are_normalized_to_linux_line_endings(self):
        harness = (Path(__file__).parents[1] / "scripts" / "ally-remote-test.ps1").read_text()
        remote_start = harness.index("function Invoke-RemoteScript")
        remote_end = harness.index("function Find-RemotePluginDirectory", remote_start)
        remote_runner = harness[remote_start:remote_end]

        self.assertIn(
            '$normalizedScript = $Script.Replace("`r`n", "`n").Replace("`r", "`n")',
            remote_runner,
        )
        self.assertIn("GetBytes($normalizedScript)", remote_runner)
        self.assertNotIn("GetBytes($Script)", remote_runner)

    def test_snapshot_prefers_active_runtime_config_over_legacy_state(self):
        harness = (Path(__file__).parents[1] / "scripts" / "ally-remote-test.ps1").read_text()
        snapshot_start = harness.index("function Save-Snapshot")
        snapshot_end = harness.index("function Invoke-Preflight", snapshot_start)
        snapshot = harness[snapshot_start:snapshot_end]

        runtime_check = 'if test -r "`$PLUGIN_DIR/`$file"; then'
        state_fallback = 'elif test -r "`$STATE_DIR/`$file"; then'
        self.assertIn(runtime_check, snapshot)
        self.assertIn(state_fallback, snapshot)
        self.assertLess(snapshot.index(runtime_check), snapshot.index(state_fallback))

    def test_deployment_stages_outside_decky_plugin_scan_directory(self):
        harness = (Path(__file__).parents[1] / "scripts" / "ally-remote-test.ps1").read_text()
        deploy_start = harness.index("function Invoke-Deploy")
        deploy = harness[deploy_start:]

        self.assertIn('STAGING="`$BACKUP_ROOT/.staging-`$STAMP"', deploy)
        self.assertNotIn('STAGING="`$PLUGIN_DIR.staging-`$STAMP"', deploy)
        self.assertIn("egpu_identity.json", deploy)

    def test_deployment_normalizes_shell_executables_before_plugin_swap(self):
        harness = (Path(__file__).parents[1] / "scripts" / "ally-remote-test.ps1").read_text()
        deploy_start = harness.index("function Invoke-Deploy")
        deploy = harness[deploy_start:]

        normalize = "sed -i 's/\\r`$//' \"`$executable\""
        swap = 'if test -d "`$PLUGIN_DIR"; then mv "`$PLUGIN_DIR" "`$BACKUP"; fi'
        self.assertIn(normalize, deploy)
        self.assertIn("Refusing deployment: CRLF remains in executable", deploy)
        self.assertLess(deploy.index(normalize), deploy.index(swap))

    def test_gamescope_wrapper_is_stored_with_linux_line_endings(self):
        wrapper = (Path(__file__).parents[1] / "bin" / "gamescope").read_bytes()

        self.assertTrue(wrapper.startswith(b"#!/bin/bash\n"))
        self.assertNotIn(b"\r\n", wrapper)

    def test_live_capture_suppresses_repetitive_smu_metrics_flood(self):
        harness = (Path(__file__).parents[1] / "scripts" / "ally-remote-test.ps1").read_text()

        self.assertIn(
            "grep --line-buffered -Eiv 'Failed to export SMU metrics table|TransferTableSmu2Dram'",
            harness,
        )

    def test_live_capture_preserves_raw_aer_evidence_and_summarizes_the_console(self):
        harness = (Path(__file__).parents[1] / "scripts" / "ally-remote-test.ps1").read_text()
        capture_start = harness.index("function Invoke-Capture")
        deploy_start = harness.index("function Invoke-Deploy", capture_start)
        capture = harness[capture_start:deploy_start]

        self.assertIn("Tee-Object -FilePath $capturePath", capture)
        self.assertIn("Write-CaptureConsoleLine", capture)
        self.assertLess(
            capture.index("Tee-Object -FilePath $capturePath"),
            capture.index("Write-CaptureConsoleLine"),
        )
        self.assertIn("main.collect_pcie_link_health()", capture)
        self.assertIn("full records remain in live.txt", harness)


def status(*, connector="HDMI-A-1", output_order="", gamescope=""):
    return {
        "egpu": {"card": "card1"},
        "recommended_connector": {"name": connector, "status": "connected"},
        "patch_state": {"output_order": output_order},
        "gamescope": gamescope,
    }


class DisplayTargetTests(unittest.TestCase):
    def test_gpd_g1_uses_its_actual_gpu_model_name(self):
        self.assertEqual(
            main._gpu_pretty_name(
                {
                    "vendor": "0x1002",
                    "device": "0x7480",
                    "lspci": "Navi 33",
                }
            ),
            "AMD Radeon RX 7600M XT",
        )

    def test_connected_external_display_is_not_assumed_active(self):
        self.assertEqual(main._display_target_label(status()), "internal")

    def test_configured_hdmi_connector_is_external(self):
        self.assertEqual(
            main._display_target_label(status(output_order="HDMI-A-1")),
            "external",
        )

    def test_live_displayport_connector_is_external(self):
        self.assertEqual(
            main._display_target_label(
                status(connector="DP-2", gamescope="gamescope --prefer-output 'DP-2' -e")
            ),
            "external",
        )

    def test_live_internal_output_wins_over_stale_external_config(self):
        self.assertEqual(
            main._display_target_label(
                status(output_order="HDMI-A-1", gamescope="gamescope -O *,eDP-1 -e")
            ),
            "internal",
        )

    def test_hotplug_presence_changes_emit_structured_arrival_and_removal_events(self):
        disconnected = {"connected": False, "egpu": None}
        connected = {
            "connected": True,
            "egpu": {"pci": "0000:08:00.0", "vendor": "0x1002", "device": "0x7480"},
        }
        with mock.patch.object(main, "log_event") as event_mock:
            main._record_device_presence_transition(disconnected, connected)
            main._record_device_presence_transition(connected, connected)
            main._record_device_presence_transition(connected, disconnected)

        self.assertEqual(event_mock.call_count, 2)
        self.assertEqual(event_mock.call_args_list[0].args[0], "device.arrived")
        self.assertEqual(event_mock.call_args_list[1].args[0], "device.removed")


class SystemCommandTests(unittest.TestCase):
    def test_mesa_version_is_cached_across_status_refreshes(self):
        completed = {"ok": True, "out": "mesa 25.3.0.213835.radeonsi_25.3.0-4.1"}
        with mock.patch.object(main, "run", return_value=completed) as run_mock, mock.patch.object(
            main.time, "monotonic", side_effect=[100.0, 105.0, 401.0]
        ), mock.patch.dict(
            main._mesa_version_cache, {"value": "", "checked_at": 0.0}, clear=True
        ):
            self.assertEqual(main._get_mesa_version(), "25.3")
            self.assertEqual(main._get_mesa_version(), "25.3")
            self.assertEqual(main._get_mesa_version(), "25.3")

        self.assertEqual(run_mock.call_count, 2)

    def test_system_commands_drop_decky_bundled_library_environment(self):
        completed = mock.Mock(returncode=0, stdout="mesa 1.2.3\n", stderr="")
        bundled_environment = {
            "PATH": "/usr/bin",
            "LD_LIBRARY_PATH": "/tmp/_MEI123",
            "LD_PRELOAD": "/tmp/plugin.so",
            "PYTHONHOME": "/tmp/python",
            "PYTHONPATH": "/tmp/modules",
        }
        with mock.patch.dict(main.os.environ, bundled_environment, clear=True), mock.patch.object(
            main.subprocess, "run", return_value=completed
        ) as run_mock, mock.patch.object(main, "log"):
            result = main.run(["pacman", "-Q", "mesa"])

        self.assertTrue(result["ok"])
        child_environment = run_mock.call_args.kwargs["env"]
        self.assertEqual(child_environment["PATH"], "/usr/bin")
        for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
            self.assertNotIn(key, child_environment)

    def test_modetest_textual_permission_failure_overrides_zero_exit_code(self):
        result = main._normalize_modetest_write_result(
            {
                "ok": True,
                "rc": 0,
                "out": "opened device AMD GPU",
                "err": "failed to set CONNECTOR 112 property DPMS to 3: Permission denied",
            }
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["reported_failure"])

    def test_modetest_clean_zero_exit_code_remains_successful(self):
        result = main._normalize_modetest_write_result(
            {"ok": True, "rc": 0, "out": "opened device AMD GPU", "err": ""}
        )

        self.assertTrue(result["ok"])
        self.assertNotIn("reported_failure", result)


class HardwareCompatibilityTests(unittest.TestCase):
    def test_ally_x_dmi_variant_is_recognized(self):
        values = {
            "/sys/devices/virtual/dmi/id/sys_vendor": "ASUSTeK COMPUTER INC.",
            "/sys/devices/virtual/dmi/id/product_name": "ROG Ally X RC72LA_RC72LA",
        }
        with mock.patch.object(main, "_read_text", side_effect=lambda path: values.get(str(path), "")):
            hint = main.detect_device_hint()

        self.assertTrue(hint["known"])
        self.assertEqual(hint["friendly_name"], "ASUS ROG Ally X")

    def test_validated_ally_x_g1_pair_reports_sleep_warning(self):
        warning = main._sleep_compatibility_status(
            {
                "device_hint": {
                    "vendor": "ASUSTeK COMPUTER INC.",
                    "product_name": "ROG Ally X RC72LA_RC72LA",
                    "friendly_name": "ASUS ROG Ally X",
                },
                "egpu": {"vendor": "0x1002", "device": "0x7480"},
            }
        )

        self.assertTrue(warning["warning"])
        self.assertEqual(warning["code"], "ally_x_gpd_g1_immediate_acpi_wake")

    def test_unvalidated_hardware_does_not_report_sleep_warning(self):
        warning = main._sleep_compatibility_status(
            {
                "device_hint": {"friendly_name": "Steam Deck OLED"},
                "egpu": {"vendor": "0x1002", "device": "0x7480"},
            }
        )

        self.assertFalse(warning["warning"])


class StableEgpuIdentityTests(unittest.IsolatedAsyncioTestCase):
    def _egpu(self, pci="0000:08:00.0", card="card1"):
        return {
            "card": card,
            "path": f"/dev/dri/{card}",
            "pci": pci,
            "vendor": "0x1002",
            "device": "0x7480",
            "is_egpu": True,
            "connectors": [{"name": "HDMI-A-1", "status": "connected"}],
        }

    def _inventory(self):
        root = "/sys/devices/pci0000:00/0000:00:03.1/0000:04:00.0"

        def item(pci, suffix, vendor, device, device_class, driver="pcieport", removable=False):
            return {
                "pci": pci,
                "real_path": root + suffix,
                "vendor": vendor,
                "device": device,
                "class": device_class,
                "driver": driver,
                "remove_path": f"/sys/bus/pci/devices/{pci}/remove",
                "remove_available": removable,
            }

        return [
            item("0000:04:00.0", "", "0x8086", "0x15ef", "0x060400", removable=True),
            item("0000:05:01.0", "/0000:05:01.0", "0x8086", "0x15ef", "0x060400"),
            item("0000:05:02.0", "/0000:05:02.0", "0x8086", "0x15ef", "0x060400"),
            item("0000:06:00.0", "/0000:05:01.0/0000:06:00.0", "0x1002", "0x1478", "0x060400"),
            item("0000:07:00.0", "/0000:05:01.0/0000:06:00.0/0000:07:00.0", "0x1002", "0x1479", "0x060400"),
            item("0000:08:00.0", "/0000:05:01.0/0000:06:00.0/0000:07:00.0/0000:08:00.0", "0x1002", "0x7480", "0x030000", "amdgpu"),
            item("0000:08:00.1", "/0000:05:01.0/0000:06:00.0/0000:07:00.0/0000:08:00.1", "0x1002", "0xab30", "0x040300", "snd_hda_intel"),
            item("0000:09:00.0", "/0000:05:02.0/0000:09:00.0", "0x8086", "0x15f0", "0x0c0330", "xhci_hcd"),
        ]

    def _thunderbolt(self):
        return {
            "ok": True,
            "complete": True,
            "device": {
                "id": "0-2",
                "name": "Tapex Creek",
                "vendor": "Intel",
                "authorized": "1",
                "unique_id": "private-g1-test-id",
            },
        }

    def test_validated_g1_identity_hashes_the_usb4_unique_id(self):
        with mock.patch.object(main, "_gpd_g1_thunderbolt_device", return_value=self._thunderbolt()):
            result = main._validated_gpd_g1_identity(self._egpu(), self._inventory())

        self.assertTrue(result["validated"])
        encoded = json.dumps(result)
        self.assertNotIn("private-g1-test-id", encoded)
        self.assertRegex(result["identity"]["thunderbolt_unique_id_sha256"], r"^[0-9a-f]{64}$")

    def test_persisted_identity_resolves_only_the_exact_g1(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            main, "_gpd_g1_thunderbolt_device", return_value=self._thunderbolt()
        ), mock.patch.object(main, "log_event"):
            path = Path(tmp) / "egpu_identity.json"
            observed = main._validated_gpd_g1_identity(self._egpu(), self._inventory())["identity"]
            persisted = main._persist_egpu_identity(observed, path)
            persisted_text = path.read_text(encoding="utf-8")
            resolved = main._resolve_egpu_for_switch(
                [self._egpu()],
                identity_path=path,
                pci_inventory=self._inventory(),
            )
            wrong_slot = main._resolve_egpu_for_switch(
                [self._egpu("0000:0a:00.0")],
                identity_path=path,
                pci_inventory=self._inventory(),
            )

        self.assertTrue(persisted["persisted"])
        self.assertNotIn("private-g1-test-id", persisted_text)
        self.assertTrue(resolved["bound"])
        self.assertEqual(resolved["card"]["pci"], "0000:08:00.0")
        self.assertFalse(wrong_slot["ok"])
        self.assertEqual(wrong_slot["error_code"], "bound_egpu_missing")

    def test_unverified_g1_topology_fails_closed_before_switching(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            main, "_gpd_g1_thunderbolt_device", return_value=self._thunderbolt()
        ):
            result = main._resolve_egpu_for_switch(
                [self._egpu()],
                identity_path=Path(tmp) / "missing.json",
                pci_inventory=[],
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "gpd_g1_topology_unverified")

    async def test_ambiguous_external_gpus_are_rejected_before_configuration_changes(self):
        detected = {
            "cards": [self._egpu(), self._egpu("0000:0a:00.0", "card2")],
            "egpu": self._egpu(),
            "recommended_connector": {"name": "HDMI-A-1", "status": "connected"},
            "gamescope": "88 gamescope -O *,eDP-1",
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            main, "EGPU_IDENTITY_PATH", Path(tmp) / "missing.json"
        ), mock.patch.object(main, "build_status", return_value=detected), mock.patch.object(
            main, "write_gamescope_wrapper_config"
        ) as config_mock:
            result = await main.Plugin.apply_egpu_mode(restart=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "egpu_identity_ambiguous")
        config_mock.assert_not_called()


class GamescopeEnvironmentTests(unittest.TestCase):
    def test_root_backend_updates_the_gamescope_users_systemd_manager(self):
        with mock.patch.object(
            main,
            "_gamescope_user_context",
            return_value={"username": "ally", "uid": 1000, "source": "test"},
        ), mock.patch.object(main.os, "geteuid", return_value=0, create=True), mock.patch.object(
            main, "run", return_value={"ok": True, "rc": 0, "out": "", "err": ""}
        ) as run_mock:
            result = main.update_gamescope_user_environment(
                values={"MESA_VK_DEVICE_SELECT": "1002:7480"}
            )

        self.assertTrue(result["ok"])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:4], ["/usr/bin/runuser", "-u", "ally", "--"])
        self.assertIn("--user", command)
        self.assertEqual(command[-2:], ["set-environment", "MESA_VK_DEVICE_SELECT=1002:7480"])

    def test_restore_unsets_the_device_selection(self):
        with mock.patch.object(
            main,
            "_gamescope_user_context",
            return_value={"username": "ally", "uid": 1000, "source": "test"},
        ), mock.patch.object(main.os, "geteuid", return_value=0, create=True), mock.patch.object(
            main, "run", return_value={"ok": True, "rc": 0, "out": "", "err": ""}
        ) as run_mock:
            result = main.update_gamescope_user_environment(
                unset=["MESA_VK_DEVICE_SELECT"]
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            run_mock.call_args.args[0][-2:],
            ["unset-environment", "MESA_VK_DEVICE_SELECT"],
        )


class ApplyModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_amd_apply_sets_mesa_device_selection(self):
        detected = {
            "egpu": {"vendor": "0x1002", "device": "0x7480"},
            "recommended_connector": {"name": "HDMI-A-2", "status": "connected"},
        }
        with mock.patch.object(main, "build_status", return_value=detected), mock.patch.object(
            main,
            "write_gamescope_wrapper_config",
            return_value={"ok": True},
        ) as config_mock, mock.patch.object(
            main,
            "update_gamescope_user_environment",
            return_value={"ok": True, "steps": []},
        ) as env_mock:
            result = await main.Plugin.apply_egpu_mode(restart=False)

        self.assertTrue(result["ok"])
        config_mock.assert_called_once_with("HDMI-A-2", "1002:7480")
        env_mock.assert_called_once_with(values={"MESA_VK_DEVICE_SELECT": "1002:7480"})

    async def test_restart_is_skipped_when_exact_external_state_is_live(self):
        detected = {
            "egpu": {
                "card": "card1",
                "pci": "0000:65:00.0",
                "vendor": "0x1002",
                "device": "0x7480",
            },
            "recommended_connector": {"name": "HDMI-A-2", "status": "connected"},
            "gamescope": "420 gamescope -O HDMI-A-2 --prefer-vk-device 1002:7480 -e",
        }
        with mock.patch.object(main, "build_status", return_value=detected), mock.patch.object(
            main, "_running_steam_games", return_value={"ok": True, "games": [], "count": 0}
        ) as running_mock, mock.patch.object(
            main, "ensure_gamescope_integration", return_value={"ok": True}
        ), mock.patch.object(
            main, "write_gamescope_wrapper_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "update_gamescope_user_environment", return_value={"ok": True, "steps": []}
        ), mock.patch.object(main, "_apply_restart_sync") as restart_mock:
            result = await main.Plugin.apply_egpu_mode(restart=True)

        self.assertTrue(result["ok"])
        self.assertTrue(result["restart_skipped"])
        running_mock.assert_not_called()
        restart_mock.assert_not_called()

    async def test_running_game_blocks_session_restart_before_configuration_changes(self):
        detected = {
            "egpu": {
                "card": "card1",
                "pci": "0000:65:00.0",
                "vendor": "0x1002",
                "device": "0x7480",
            },
            "recommended_connector": {"name": "HDMI-A-2", "status": "connected"},
            "gamescope": "420 gamescope -O *,eDP-1 -e",
        }
        running = {
            "ok": True,
            "games": [{"appid": 1234, "unit": "app-steam-1234.scope"}],
            "count": 1,
        }
        with mock.patch.object(main, "build_status", return_value=detected), mock.patch.object(
            main, "_running_steam_games", return_value=running
        ), mock.patch.object(main, "ensure_gamescope_integration") as integration_mock, mock.patch.object(
            main, "write_gamescope_wrapper_config"
        ) as config_mock:
            result = await main.Plugin.apply_egpu_mode(restart=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "running_game")
        self.assertTrue(result["requires_confirmation"])
        integration_mock.assert_not_called()
        config_mock.assert_not_called()

    async def test_reload_fails_closed_when_running_game_check_is_unavailable(self):
        detected = {
            "egpu": {
                "card": "card1",
                "pci": "0000:65:00.0",
                "vendor": "0x1002",
                "device": "0x7480",
            },
            "recommended_connector": {"name": "HDMI-A-2", "status": "connected"},
            "gamescope": "420 gamescope -O *,eDP-1 -e",
        }
        check = {"ok": False, "games": [], "count": 0, "check": {"err": "user bus unavailable"}}
        with mock.patch.object(main, "build_status", return_value=detected), mock.patch.object(
            main, "_running_steam_games", return_value=check
        ), mock.patch.object(main, "ensure_gamescope_integration") as integration_mock, mock.patch.object(
            main, "write_gamescope_wrapper_config"
        ) as config_mock:
            result = await main.Plugin.apply_egpu_mode(restart=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "running_game_check_failed")
        integration_mock.assert_not_called()
        config_mock.assert_not_called()

    async def test_native_handoff_returns_before_scheduled_restart(self):
        detected = {
            "egpu": {
                "card": "card1",
                "pci": "0000:65:00.0",
                "vendor": "0x1002",
                "device": "0x7480",
            },
            "recommended_connector": {"name": "HDMI-A-2", "status": "connected"},
            "gamescope": "420 gamescope -O *,eDP-1 -e",
        }
        transition = {"id": "transition-1", "status": "pending", "target": "external"}
        with mock.patch.object(main, "build_status", return_value=detected), mock.patch.object(
            main, "_running_steam_games", return_value={"ok": True, "games": [], "count": 0}
        ), mock.patch.object(
            main, "ensure_gamescope_integration", return_value={"ok": True}
        ), mock.patch.object(
            main, "write_gamescope_wrapper_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "update_gamescope_user_environment", return_value={"ok": True, "steps": []}
        ), mock.patch.object(
            main, "_write_display_transition", return_value=transition
        ), mock.patch.object(
            main,
            "_schedule_display_restart",
            return_value={"ok": True, "accepted": True, "transition_id": "transition-1"},
        ) as schedule_mock, mock.patch.object(main, "_apply_restart_sync") as restart_mock:
            result = await main.Plugin.apply_egpu_mode(restart=True, async_handoff=True)

        self.assertTrue(result["ok"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["transition"]["id"], "transition-1")
        schedule_mock.assert_called_once()
        restart_mock.assert_not_called()


class NativeHandoffWrapperTests(unittest.IsolatedAsyncioTestCase):
    def test_deferred_restart_leaves_time_for_the_rpc_response(self):
        delay = inspect.signature(main._schedule_display_restart).parameters["delay_s"].default
        self.assertEqual(delay, 1.0)

    async def test_deferred_internal_handoff_does_not_delay_rpc_for_tv_power(self):
        accepted = {"ok": True, "accepted": True, "transition": {"id": "transition-2"}}
        with mock.patch.object(
            main,
            "_egb_81103_call_old",
            new=mock.AsyncMock(return_value=accepted),
        ), mock.patch.object(
            main,
            "_egb_81103_maybe_tv_off_after_internal",
            new=mock.AsyncMock(),
        ) as tv_off_mock:
            result = await main._egb_81103_restore_internal_mode(
                restart=True,
                async_handoff=True,
            )

        self.assertTrue(result["accepted"])
        self.assertEqual(
            result["wifi_tv_auto_tv_off"]["reason"],
            "deferred-display-transition",
        )
        tv_off_mock.assert_not_awaited()


class GamescopeDesiredStateTests(unittest.TestCase):
    def test_external_state_requires_both_output_and_exact_gpu(self):
        desired = {
            "target": "external",
            "connector": "HDMI-A-2",
            "output_order": "HDMI-A-2",
            "prefer_vk_device": "1002:7480",
            "mode": {},
        }
        self.assertTrue(
            main._gamescope_matches_desired(
                "77 gamescope -O HDMI-A-2 --prefer-vk-device 1002:7480 -e",
                desired,
            )
        )
        self.assertFalse(
            main._gamescope_matches_desired(
                "77 gamescope -O HDMI-A-2 --prefer-vk-device 1002:7550 -e",
                desired,
            )
        )

    def test_internal_state_rejects_stale_external_gpu_preference(self):
        desired = {
            "target": "internal",
            "output_order": "*,eDP-1",
            "prefer_vk_device": "disabled",
            "mode": {},
        }
        self.assertTrue(main._gamescope_matches_desired("81 gamescope -O *,eDP-1 -e", desired))
        self.assertFalse(
            main._gamescope_matches_desired(
                "81 gamescope -O *,eDP-1 --prefer-vk-device 1002:7480 -e",
                desired,
            )
        )

    def test_requested_mode_must_match_live_arguments(self):
        desired = {
            "target": "external",
            "connector": "HDMI-A-2",
            "output_order": "HDMI-A-2",
            "prefer_vk_device": "1002:7480",
            "mode": {"width": 1920, "height": 1080, "refresh": 60},
        }
        self.assertTrue(
            main._gamescope_matches_desired(
                "90 gamescope -O HDMI-A-2 --prefer-vk-device 1002:7480 -W 1920 -H 1080 -r 60",
                desired,
            )
        )
        self.assertFalse(
            main._gamescope_matches_desired(
                "90 gamescope -O HDMI-A-2 --prefer-vk-device 1002:7480 -W 3840 -H 2160 -r 60",
                desired,
            )
        )


class RunningGameTests(unittest.TestCase):
    def test_only_steam_game_scopes_trigger_the_reload_guard(self):
        units = """\
app-steam-1234.scope loaded active running Game 1234
steam-app-5678.scope loaded active running Game 5678
app-com.valvesoftware.Steam.scope loaded active running Steam
gamescope-session.scope loaded active running Gamescope
"""
        context = {"username": "ally", "uid": 1000, "source": "test"}
        with mock.patch.object(main, "_gamescope_user_context", return_value=context), mock.patch.object(
            main, "run", return_value={"ok": True, "rc": 0, "out": units, "err": ""}
        ):
            result = main._running_steam_games()

        self.assertEqual(result["count"], 2)
        self.assertEqual([game["appid"] for game in result["games"]], [1234, 5678])


class GamescopeRestartTests(unittest.TestCase):
    def test_live_readiness_can_succeed_when_systemctl_times_out(self):
        timeout = main.subprocess.TimeoutExpired(["systemctl"], 20)
        ready = {"ok": True, "ready": True, "current_pids": [22]}
        with mock.patch.object(
            main,
            "_gamescope_user_context",
            return_value={"username": "ally", "uid": 1000, "source": "test"},
        ), mock.patch.object(main, "current_gamescope_process", return_value="11 gamescope -O *,eDP-1"), mock.patch.object(
            main, "_gamescope_pids", return_value=[11]
        ), mock.patch.object(main.subprocess, "run", side_effect=timeout), mock.patch.object(
            main, "_wait_for_gamescope_ready", return_value=ready
        ):
            result = main.restart_gamescope_session_target({"target": "internal"})

        self.assertTrue(result["ok"])
        self.assertFalse(result["systemctl_ok"])
        self.assertIn("timed out", result["err"])
        self.assertIn("total_elapsed_seconds", result)
        self.assertEqual(
            result["readiness"]["total_elapsed_seconds"],
            result["total_elapsed_seconds"],
        )


class DisplayTransitionRollbackTests(unittest.TestCase):
    @staticmethod
    def _finish(transition, status, details=None):
        result = dict(transition)
        result["status"] = status
        result["details"] = details
        return result

    def test_failed_external_restart_rolls_back_persisted_state_without_an_extra_restart(self):
        external = {
            "target": "external",
            "connector": "HDMI-A-1",
            "output_order": "HDMI-A-1",
            "prefer_vk_device": "1002:7480",
            "mode": {},
        }
        transition = {"id": "external-1", "status": "pending", "target": "external"}
        failed = {"ok": False, "readiness": {"error": "external display timed out"}}
        with mock.patch.object(main, "hdmi_panel_on", return_value={"ok": True}), mock.patch.object(
            main, "restart_gamescope_session_target", return_value=failed
        ) as restart_mock, mock.patch.object(
            main, "write_gamescope_wrapper_config", return_value={"ok": True}
        ) as config_mock, mock.patch.object(
            main, "write_gamescope_mode_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "update_gamescope_user_environment", return_value={"ok": True}
        ) as environment_mock, mock.patch.object(
            main, "current_gamescope_process", return_value="88 gamescope -O *,eDP-1 -e"
        ), mock.patch.object(main, "internal_panel_on", return_value={"ok": True}), mock.patch.object(
            main, "hdmi_panel_off", return_value={"ok": True}
        ), mock.patch.object(
            main, "_finish_display_transition", side_effect=self._finish
        ), mock.patch.object(main, "log_event"):
            result = main._apply_restart_sync(external, transition)

        self.assertFalse(result["ok"])
        self.assertTrue(result["rollback"]["ok"])
        self.assertEqual(result["transition"]["status"], "rolled_back")
        config_mock.assert_called_once_with("*,eDP-1", "disabled")
        environment_mock.assert_called_once_with(unset=["MESA_VK_DEVICE_SELECT"])
        restart_mock.assert_called_once_with(external)
        json.dumps(result)

    def test_external_rollback_restarts_gamescope_when_internal_state_is_not_live(self):
        transition = {"id": "external-2", "status": "pending", "target": "external"}
        with mock.patch.object(
            main, "write_gamescope_wrapper_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "write_gamescope_mode_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "update_gamescope_user_environment", return_value={"ok": True}
        ), mock.patch.object(
            main, "current_gamescope_process", return_value="99 gamescope -O HDMI-A-1 --prefer-vk-device 1002:7480"
        ), mock.patch.object(main, "internal_panel_on", return_value={"ok": True}), mock.patch.object(
            main, "hdmi_panel_off", return_value={"ok": True}
        ), mock.patch.object(
            main, "restart_gamescope_session_target", return_value={"ok": True, "readiness": {"ready": True}}
        ) as restart_mock, mock.patch.object(
            main, "_finish_display_transition", side_effect=self._finish
        ), mock.patch.object(main, "log_event"):
            result = main._rollback_external_transition(transition, {"error": "timeout"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["transition"]["status"], "rolled_back")
        restart_mock.assert_called_once_with(main._internal_display_desired())

    def test_external_rollback_fails_closed_when_environment_cannot_be_cleared(self):
        transition = {"id": "external-3", "status": "pending", "target": "external"}
        with mock.patch.object(
            main, "write_gamescope_wrapper_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "write_gamescope_mode_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "update_gamescope_user_environment", return_value={"ok": False, "error": "no user bus"}
        ), mock.patch.object(main, "current_gamescope_process", return_value=""), mock.patch.object(
            main, "internal_panel_on", return_value={"ok": True}
        ), mock.patch.object(main, "restart_gamescope_session_target") as restart_mock, mock.patch.object(
            main, "_finish_display_transition", side_effect=self._finish
        ), mock.patch.object(main, "log_event"):
            result = main._rollback_external_transition(transition, {"error": "timeout"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["transition"]["status"], "rollback_failed")
        restart_mock.assert_not_called()

    def test_stale_external_transition_is_reconciled_through_rollback(self):
        transition = {
            "id": "external-4",
            "status": "pending",
            "target": "external",
            "desired": {"target": "external", "connector": "HDMI-A-1"},
            "created_at": 100.0,
        }
        rolled_back = dict(transition, status="rolled_back")
        with mock.patch.object(main, "_read_display_transition", return_value=transition), mock.patch.object(
            main, "_gamescope_matches_desired", return_value=False
        ), mock.patch.object(main.time, "time", return_value=150.0), mock.patch.object(
            main,
            "_rollback_external_transition",
            return_value={"ok": True, "transition": rolled_back},
        ) as rollback_mock:
            result = main.reconcile_display_transition("88 gamescope -O *,eDP-1")

        self.assertEqual(result["status"], "rolled_back")
        rollback_mock.assert_called_once()


class MissingEgpuRecoveryTests(unittest.TestCase):
    def test_internal_shim_failback_replaces_stale_external_configuration(self):
        status_payload = {
            "egpu": None,
            "gamescope": "22 gamescope -O *,eDP-1",
            "patch_state": {
                "output_order": "HDMI-A-1",
                "prefer_vk_device": "1002:7480",
            },
        }
        with mock.patch.object(
            main,
            "write_gamescope_wrapper_config",
            return_value={"ok": True},
        ) as config_mock, mock.patch.object(
            main,
            "write_gamescope_mode_config",
            return_value={"ok": True},
        ), mock.patch.object(
            main,
            "update_gamescope_user_environment",
            return_value={"ok": True},
        ) as environment_mock:
            result = main.reconcile_missing_egpu_configuration(status_payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        config_mock.assert_called_once_with("*,eDP-1", "disabled")
        environment_mock.assert_called_once_with(unset=["MESA_VK_DEVICE_SELECT"])

    def test_present_egpu_does_not_rewrite_configuration(self):
        with mock.patch.object(main, "write_gamescope_wrapper_config") as config_mock:
            result = main.reconcile_missing_egpu_configuration(
                {"egpu": {"pci": "0000:08:00.0"}, "gamescope": "gamescope -O HDMI-A-1"}
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        config_mock.assert_not_called()


class ResumeRecoveryTests(unittest.TestCase):
    def test_login1_prepare_for_sleep_signal_parser(self):
        self.assertTrue(
            main._parse_prepare_for_sleep_signal(
                "/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)"
            )
        )
        self.assertFalse(
            main._parse_prepare_for_sleep_signal(
                "/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (false,)"
            )
        )
        self.assertIsNone(main._parse_prepare_for_sleep_signal("PreparingForSleep: true"))

    def test_resume_watcher_detects_a_short_s2idle_cycle(self):
        stop_event = mock.Mock()
        stop_event.wait.side_effect = [False, False, True]
        with mock.patch.object(
            main,
            "_suspend_inclusive_clock",
            side_effect=[
                (100.0, "boottime_monotonic_gap"),
                (104.0, "boottime_monotonic_gap"),
            ],
        ), mock.patch.object(
            main.time, "monotonic", side_effect=[50.0, 51.0]
        ), mock.patch.object(main, "_write_resume_state") as state_mock, mock.patch.object(
            main, "_recover_after_resume"
        ) as recover_mock, mock.patch.object(
            main, "_resume_last_detection_monotonic", 0.0
        ):
            main._resume_watcher_loop(stop_event)

        state_mock.assert_called_once_with(
            "resume_detected",
            {
                "source": "boottime_monotonic_gap",
                "suspended_seconds": 3.0,
            },
        )
        recover_mock.assert_called_once_with(stop_event=stop_event)
        self.assertEqual(
            stop_event.wait.call_args_list[:2],
            [
                mock.call(main.RESUME_POLL_INTERVAL_SECONDS),
                mock.call(main.RESUME_DIRECT_EVENT_GRACE_SECONDS),
            ],
        )

    def test_direct_and_fallback_resume_detections_are_debounced(self):
        with mock.patch.object(
            main, "_resume_last_detection_monotonic", 0.0
        ), mock.patch.object(main, "_write_resume_state") as state_mock, mock.patch.object(
            main, "_recover_after_resume", return_value={"ok": True}
        ) as recover_mock:
            first = main._handle_resume_detection(
                "login1_prepare_for_sleep",
                suspended_seconds=0.2,
                detected_monotonic=100.0,
            )
            duplicate = main._handle_resume_detection(
                "boottime_monotonic_gap",
                suspended_seconds=1.1,
                detected_monotonic=101.0,
            )

        self.assertTrue(first["ok"])
        self.assertTrue(duplicate["skipped"])
        self.assertEqual(duplicate["reason"], "duplicate_resume_detection")
        state_mock.assert_called_once()
        recover_mock.assert_called_once()

    def test_resume_recovery_cancels_cleanly_during_plugin_unload(self):
        stop_event = mock.Mock()
        stop_event.is_set.return_value = True
        with mock.patch.object(
            main, "_configured_external_vk_device", return_value="1002:7480"
        ), mock.patch.object(
            main, "_write_resume_state", side_effect=lambda status, details=None: {
                "status": status,
                "details": details or {},
            }
        ), mock.patch.object(main, "write_gamescope_wrapper_config") as config_mock:
            result = main._recover_after_resume(
                enumeration_timeout_s=20,
                stop_event=stop_event,
            )

        self.assertEqual(result["status"], "resume_recovery_cancelled")
        config_mock.assert_not_called()

    def test_resume_keeps_external_configuration_when_exact_egpu_returns(self):
        with mock.patch.object(
            main, "_configured_external_vk_device", return_value="1002:7480"
        ), mock.patch.object(
            main, "_pci_vendor_device_present", return_value=True
        ), mock.patch.object(
            main, "_write_resume_state", side_effect=lambda status, details=None: {
                "status": status,
                "details": details or {},
            }
        ), mock.patch.object(main, "write_gamescope_wrapper_config") as config_mock:
            result = main._recover_after_resume(enumeration_timeout_s=0)

        self.assertEqual(result["status"], "resume_egpu_present")
        config_mock.assert_not_called()

    def test_resume_restores_internal_when_configured_egpu_is_absent(self):
        ready = {"ok": True, "readiness": {"ok": True}}
        with mock.patch.object(
            main, "_configured_external_vk_device", return_value="1002:7480"
        ), mock.patch.object(
            main, "_pci_vendor_device_present", return_value=False
        ), mock.patch.object(
            main, "_write_resume_state", side_effect=lambda status, details=None: {
                "status": status,
                "details": details or {},
            }
        ), mock.patch.object(
            main, "write_gamescope_wrapper_config", return_value={"ok": True}
        ) as config_mock, mock.patch.object(
            main, "write_gamescope_mode_config", return_value={"ok": True}
        ), mock.patch.object(
            main, "update_gamescope_user_environment", return_value={"ok": True}
        ) as environment_mock, mock.patch.object(
            main, "internal_panel_on", return_value={"ok": True}
        ), mock.patch.object(
            main,
            "current_gamescope_process",
            return_value="77 gamescope -O HDMI-A-2 --prefer-vk-device 1002:7480",
        ), mock.patch.object(
            main, "_write_display_transition", return_value={"id": "resume-1"}
        ), mock.patch.object(
            main, "restart_gamescope_session_target", return_value=ready
        ) as restart_mock, mock.patch.object(
            main, "_finish_display_transition", return_value={"status": "completed"}
        ):
            result = main._recover_after_resume(enumeration_timeout_s=0)

        self.assertEqual(result["status"], "resume_recovered_internal")
        config_mock.assert_called_once_with("*,eDP-1", "disabled")
        environment_mock.assert_called_once_with(unset=["MESA_VK_DEVICE_SELECT"])
        restart_mock.assert_called_once()


class GamescopeIntegrationTests(unittest.TestCase):
    def test_status_reports_an_unreadable_user_config_without_raising(self):
        context = {
            "username": "restricted",
            "uid": 1000,
            "gid": 1000,
            "home": "/home/restricted",
            "source": "test",
        }
        with mock.patch.object(main, "_gamescope_dropin_path") as path_mock:
            path_mock.return_value.exists.side_effect = PermissionError("permission denied")
            result = main.gamescope_integration_status(context)

        self.assertFalse(result["ok"])
        self.assertFalse(result["dropin_installed"])
        self.assertIn("permission denied", result["error"])

    def test_install_uses_a_user_dropin_and_never_replaces_the_system_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugin"
            shim = plugin_dir / "bin" / "gamescope"
            shim.parent.mkdir(parents=True)
            shim.write_text("#!/bin/bash\n# eGPUBridge Gamescope argument shim\n")
            context = {
                "username": "ally",
                "uid": 1000,
                "gid": 1000,
                "home": str(root / "home" / "ally"),
                "source": "test",
            }

            def fake_run(command, timeout=12):
                if "show" in command:
                    return {"ok": True, "rc": 0, "out": "loaded", "err": "", "cmd": command}
                return {"ok": True, "rc": 0, "out": "", "err": "", "cmd": command}

            with mock.patch.object(main, "PLUGIN_DIR", plugin_dir), mock.patch.object(
                main, "GAMESCOPE_SHIM", shim
            ), mock.patch.object(
                main, "_gamescope_user_context", return_value=context
            ), mock.patch.object(
                main.os, "geteuid", return_value=0, create=True
            ), mock.patch.object(main.os, "chown", create=True), mock.patch.object(main, "run", side_effect=fake_run):
                result = main.ensure_gamescope_integration()

            self.assertTrue(result["ok"])
            dropin = Path(result["dropin"])
            self.assertTrue(dropin.exists())
            text = dropin.read_text()
            self.assertIn(main._systemd_environment_value(str(shim.parent)), text)
            self.assertIn("EGPUBRIDGE_PLUGIN_DIR", text)
            self.assertNotIn("ExecStart=", text)
            self.assertNotEqual(dropin, main.GAMESCOPE_SESSION)


class SafetyGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsafe_mutations_fail_closed_in_the_backend(self):
        fan = await main.gpu_set_fan_control(mode="manual", pwm=0)
        clocks = await main.gpu_set_od_clocks(sclk_mhz=9999, commit=True)
        disconnect = await main.Plugin.safe_disconnect()
        install = await main.nvidia_install_driver()

        for result in (fan, clocks, disconnect, install):
            self.assertFalse(result["ok"])
            self.assertTrue(result["disabled"])
            self.assertEqual(result["error_code"], "feature_disabled_for_safety")

    async def test_live_unplug_requires_a_fresh_readiness_token(self):
        with mock.patch.object(main, "LIVE_UNPLUG_RELEASE_ENABLED", True):
            result = await main.Plugin.safe_live_unplug({"token": "not-valid"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "readiness_token_invalid")

    async def test_live_unplug_is_quarantined_after_kernel_teardown_hang(self):
        with mock.patch.object(main, "safe_disconnect_readiness") as readiness_mock:
            result = await main.Plugin.safe_live_unplug({"token": "unused"})

        self.assertFalse(result["ok"])
        self.assertTrue(result["disabled"])
        self.assertEqual(result["error_code"], "feature_disabled_for_safety")
        readiness_mock.assert_not_called()

    async def test_frontend_replaces_dead_disconnect_control_with_readiness_report(self):
        frontend = (Path(__file__).parents[1] / "src" / "index.tsx").read_text(encoding="utf-8")

        self.assertIn('window.__egpuShowDisconnectReadiness', frontend)
        self.assertIn('call(serverApi, "safe_disconnect_readiness", {})', frontend)
        self.assertIn('"Disconnect Check"', frontend)
        self.assertIn('"Read-only check: no hardware was disconnected."', frontend)
        self.assertIn("Live release is disabled after an AMDGPU teardown hang", frontend)
        self.assertNotIn('onOKActionDescription: "Safe Disconnect eGPU"', frontend)

    async def test_frontend_refreshes_main_and_dock_status_without_overlapping(self):
        frontend = (Path(__file__).parents[1] / "src" / "index.tsx").read_text(encoding="utf-8")
        refresh_block = frontend.split("  function refresh(silent) {", 1)[1].split(
            "  function doCall(method, args) {", 1
        )[0]

        self.assertIn('call(serverApi, "status", {})', refresh_block)
        self.assertIn('call(serverApi, "dock_status", {})', refresh_block)
        self.assertIn("statusRefreshInFlightRef.current", refresh_block)
        self.assertIn("Promise.all([statusRequest, dockRequest])", refresh_block)
        self.assertIn('window.__egpuRefreshStatus', frontend)
        self.assertIn('onOKActionDescription: "Refresh eGPU status"', frontend)

    async def test_readiness_support_snapshot_never_persists_the_release_token(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            main, "DISCONNECT_READINESS_PATH", Path(tmp) / "readiness.json"
        ), mock.patch.object(main, "log"):
            main._record_disconnect_readiness({
                "ok": True,
                "ready": True,
                "token": "one-time-secret",
                "blockers": [],
                "checks": {"usb4_storage_topology": {"root_pci": "0000:04:00.0"}},
            })
            snapshot = json.loads(main.DISCONNECT_READINESS_PATH.read_text())

        self.assertNotIn("token", snapshot)
        self.assertTrue(snapshot["ready"])


class SafeDisconnectReadinessTests(unittest.TestCase):
    def tearDown(self):
        with main._live_unplug_tokens_lock:
            main._live_unplug_tokens.clear()

    def _egpu(self, pci="0000:08:00.0", card="card1"):
        return {
            "card": card,
            "path": f"/dev/dri/{card}",
            "pci": pci,
            "vendor": "0x1002",
            "device": "0x7480",
            "lspci": "VGA compatible controller: AMD RX 7600M XT",
            "is_egpu": True,
        }

    def _g1_inventory(self):
        root = "/sys/devices/pci0000:00/0000:00:03.1/0000:04:00.0"
        def item(pci, suffix, vendor, device, device_class, driver="pcieport", removable=False):
            return {
                "pci": pci,
                "real_path": root + suffix,
                "vendor": vendor,
                "device": device,
                "class": device_class,
                "driver": driver,
                "remove_path": f"/sys/bus/pci/devices/{pci}/remove",
                "remove_available": removable,
            }
        return [
            item("0000:04:00.0", "", "0x8086", "0x15ef", "0x060400", removable=True),
            item("0000:05:01.0", "/0000:05:01.0", "0x8086", "0x15ef", "0x060400"),
            item("0000:05:02.0", "/0000:05:02.0", "0x8086", "0x15ef", "0x060400"),
            item("0000:06:00.0", "/0000:05:01.0/0000:06:00.0", "0x1002", "0x1478", "0x060400"),
            item("0000:07:00.0", "/0000:05:01.0/0000:06:00.0/0000:07:00.0", "0x1002", "0x1479", "0x060400"),
            item("0000:08:00.0", "/0000:05:01.0/0000:06:00.0/0000:07:00.0/0000:08:00.0", "0x1002", "0x7480", "0x030000", "amdgpu"),
            item("0000:08:00.1", "/0000:05:01.0/0000:06:00.0/0000:07:00.0/0000:08:00.1", "0x1002", "0xab30", "0x040300", "snd_hda_intel"),
            item("0000:09:00.0", "/0000:05:02.0/0000:09:00.0", "0x8086", "0x15f0", "0x0c0330", "xhci_hcd"),
        ]

    def _readiness(self, block_devices=None, sound_clients=None, issue_token=False):
        thunderbolt = {
            "ok": True,
            "complete": True,
            "device": {
                "id": "0-2",
                "name": "Tapex Creek",
                "vendor": "Intel",
                "authorized": "1",
                "authorized_path": "/sys/bus/thunderbolt/devices/0-2/authorized",
                "unique_id": "g1-test-id",
            },
        }
        def process_scan(nodes, _proc_root=Path("/proc")):
            is_sound = any("/snd/" in str(node).replace("\\", "/") for node in nodes or [])
            return {
                "ok": True,
                "complete": True,
                "clients": list(sound_clients or []) if is_sound else [],
            }

        with mock.patch.object(
            main, "_drm_nodes_for_pci", return_value={"ok": True, "complete": True, "nodes": ["/dev/dri/card1"]}
        ), mock.patch.object(
            main, "_processes_using_device_nodes", side_effect=process_scan
        ), mock.patch.object(
            main, "_gpd_g1_thunderbolt_device", return_value=thunderbolt
        ), mock.patch.object(
            main, "_usb_devices_under_path", return_value={"ok": True, "complete": True, "devices": []}
        ), mock.patch.object(
            main,
            "_block_devices_under_path",
            return_value={"ok": True, "complete": True, "devices": list(block_devices or [])},
        ), mock.patch.object(
            main, "_class_nodes_under_path", return_value={"ok": True, "complete": True, "nodes": ["/dev/snd/controlC2"]}
        ):
            return main.safe_disconnect_readiness(
                cards=[self._egpu()],
                status_obj={"display_target": "internal", "internal_display": {"active": True}},
                pci_inventory=self._g1_inventory(),
                running_games={"ok": True, "games": [], "count": 0},
                issue_token=issue_token,
            )

    def test_ambiguous_external_gpus_fail_closed(self):
        result = main.safe_disconnect_readiness(
            cards=[self._egpu(), self._egpu("0000:09:00.0", "card2")],
            status_obj={},
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["ready"])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["blockers"][0]["code"], "egpu_identity_ambiguous")

    def test_readiness_report_hashes_the_usb4_unique_id(self):
        result = self._readiness()
        encoded = json.dumps(result)

        self.assertNotIn("g1-test-id", encoded)
        device = result["checks"]["thunderbolt_authorization"]["device"]
        self.assertRegex(device["unique_id_sha256"], r"^[0-9a-f]{64}$")

    def test_exact_drm_nodes_and_clients_are_reported_without_cmdline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sys_root = root / "sys"
            dev_root = root / "dev" / "dri"
            proc_root = root / "proc"
            pci_device = sys_root / "selected-egpu"
            drm_root = pci_device / "drm"
            drm_root.mkdir(parents=True)
            dev_root.mkdir(parents=True)
            for name in ("card1", "renderD129", "controlD65"):
                (drm_root / name).touch()
                (dev_root / name).touch()
            (drm_root / "card1-HDMI-A-1").touch()

            process = proc_root / "123"
            (process / "fd").mkdir(parents=True)
            (process / "fd" / "4").touch()
            (process / "comm").write_text("game-bin\n")

            real_readlink = os.readlink
            def fake_readlink(path):
                if Path(path) == process / "fd" / "4":
                    return str(dev_root / "renderD129")
                return real_readlink(path)

            with mock.patch.object(main.os, "readlink", side_effect=fake_readlink):
                result = main.safe_disconnect_readiness(
                    cards=[self._egpu()],
                    status_obj={"display_target": "internal", "internal_display": {"active": True}},
                    sys_pci_root=sys_root,
                    dev_dri_root=dev_root,
                    proc_root=proc_root,
                    pci_device_path=pci_device,
                )

        nodes = result["checks"]["drm_nodes"]["nodes"]
        clients = result["checks"]["drm_clients"]["clients"]
        self.assertEqual(len(nodes), 3)
        self.assertNotIn("card1-HDMI-A-1", " ".join(nodes))
        self.assertEqual(clients[0]["pid"], 123)
        self.assertEqual(clients[0]["comm"], "game-bin")
        self.assertNotIn("cmdline", clients[0])
        self.assertIn("egpu_in_use", [item["code"] for item in result["blockers"]])
        self.assertIn("usb4_topology_incomplete", [item["code"] for item in result["blockers"]])
        self.assertFalse(result["ready"])

    def test_external_display_is_a_blocker_even_with_no_clients(self):
        with mock.patch.object(
            main, "_drm_nodes_for_pci", return_value={"ok": True, "complete": True, "nodes": ["/dev/dri/card1"]}
        ), mock.patch.object(
            main, "_processes_using_device_nodes", return_value={"ok": True, "complete": True, "clients": []}
        ):
            result = main.safe_disconnect_readiness(
                cards=[self._egpu()],
                status_obj={"display_target": "external", "internal_display": {"active": False}},
            )

        codes = [item["code"] for item in result["blockers"]]
        self.assertIn("internal_display_not_verified", codes)
        self.assertFalse(result["ready"])

    def test_missing_optional_drm_control_node_does_not_block_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pci_device = root / "selected-egpu"
            drm_root = pci_device / "drm"
            dev_root = root / "dev" / "dri"
            drm_root.mkdir(parents=True)
            dev_root.mkdir(parents=True)
            for name in ("card1", "renderD129", "controlD65"):
                (drm_root / name).touch()
            (dev_root / "card1").touch()
            (dev_root / "renderD129").touch()

            result = main._drm_nodes_for_pci(
                "0000:08:00.0",
                dev_dri_root=dev_root,
                pci_device_path=pci_device,
            )

        self.assertTrue(result["complete"])
        self.assertEqual(len(result["nodes"]), 2)
        self.assertTrue(result["unavailable_optional_nodes"][0].endswith("controlD65"))

    def test_validated_g1_topology_can_issue_one_time_readiness_token(self):
        topology = main._analyze_gpd_g1_topology("0000:08:00.0", self._g1_inventory())
        self.assertTrue(topology["complete"])
        self.assertEqual(topology["root_pci"], "0000:04:00.0")
        self.assertEqual(topology["audio_pci"], ["0000:08:00.1"])
        self.assertEqual(topology["xhci_pci"], ["0000:09:00.0"])

        with mock.patch.object(main, "LIVE_UNPLUG_RELEASE_ENABLED", True):
            result = self._readiness(issue_token=True)
        self.assertTrue(result["ready"])
        self.assertTrue(result["token"])
        self.assertEqual(result["blockers"], [])

    def test_disabled_release_keeps_readiness_read_only_and_token_free(self):
        result = self._readiness(issue_token=True)

        self.assertTrue(result["ready"])
        self.assertFalse(result["release_enabled"])
        self.assertIsNone(result["token"])
        self.assertEqual(result["token_expires_in_seconds"], 0)

    def test_any_g1_storage_blocks_live_unplug_even_when_unmounted(self):
        result = self._readiness(block_devices=[{
            "name": "sda",
            "node": "/dev/sda",
            "dev": "8:0",
            "mounts": [],
            "swap": False,
        }])

        self.assertFalse(result["ready"])
        self.assertIn("external_storage_present", [item["code"] for item in result["blockers"]])

    def test_audio_control_monitor_is_allowed_but_active_pcm_is_blocked(self):
        control = {"pid": 12, "comm": "wireplumber", "nodes": ["/dev/snd/controlC2"]}
        control_result = self._readiness(sound_clients=[control])
        self.assertTrue(control_result["ready"])

        playback = {"pid": 13, "comm": "pipewire", "nodes": ["/dev/snd/pcmC2D3p"]}
        playback_result = self._readiness(sound_clients=[playback])
        self.assertFalse(playback_result["ready"])
        self.assertIn("egpu_audio_in_use", [item["code"] for item in playback_result["blockers"]])

    def test_live_unplug_rechecks_conditions_before_any_mutation(self):
        token = main._issue_live_unplug_token({"gpu_pci": "0000:08:00.0"})
        with mock.patch.object(main, "LIVE_UNPLUG_RELEASE_ENABLED", True), mock.patch.object(
            main,
            "safe_disconnect_readiness",
            return_value={"ok": True, "ready": False, "blockers": [{"code": "running_game"}]},
        ), mock.patch.object(main, "write_gamescope_wrapper_config") as write_config:
            result = main.safe_live_unplug(token)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "readiness_changed")
        write_config.assert_not_called()

    def test_live_unplug_writes_only_validated_control_paths_and_verifies_internal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pci_root = root / "pci"
            thunderbolt_root = root / "thunderbolt"
            remove_path = pci_root / "g1-root" / "remove"
            authorized_path = thunderbolt_root / "0-2" / "authorized"
            remove_path.parent.mkdir(parents=True)
            authorized_path.parent.mkdir(parents=True)
            remove_path.write_text("")
            authorized_path.write_text("1")

            fingerprint = {
                "gpu_pci": "g1-gpu",
                "root_pci": "g1-root",
                "thunderbolt_id": "0-2",
                "thunderbolt_unique_id_sha256": main._identity_sha256("g1-test-id"),
            }
            token = main._issue_live_unplug_token(fingerprint)
            readiness = {
                "ok": True,
                "ready": True,
                "identity": {"pci": "g1-gpu"},
                "checks": {
                    "usb4_storage_topology": {
                        "root_pci": "g1-root",
                        "remove_path": str(remove_path),
                    },
                    "thunderbolt_authorization": {
                        "device": {
                            "id": "0-2",
                            "name": "Tapex Creek",
                            "unique_id_sha256": main._identity_sha256("g1-test-id"),
                            "authorized_path": str(authorized_path),
                        }
                    },
                },
            }

            with mock.patch.object(main, "LIVE_UNPLUG_RELEASE_ENABLED", True), mock.patch.object(
                main, "safe_disconnect_readiness", return_value=readiness
            ), mock.patch.object(
                main, "write_gamescope_wrapper_config", return_value={"ok": True}
            ), mock.patch.object(
                main, "write_gamescope_mode_config", return_value={"ok": True}
            ), mock.patch.object(
                main, "update_gamescope_user_environment", return_value={"ok": True}
            ), mock.patch.object(
                main, "_wait_for_path_absent", return_value=True
            ), mock.patch.object(
                main, "build_status", return_value={
                    "display_target": "internal",
                    "internal_display": {"active": True},
                    "egpu": None,
                }
            ), mock.patch.object(main.os, "sync", create=True):
                result = main.safe_live_unplug(token, pci_root, thunderbolt_root)
            self.assertTrue(result["safe_to_unplug"])
            self.assertEqual(remove_path.read_text(), "1")
            self.assertEqual(authorized_path.read_text(), "0")


class InternalConnectorSafetyTests(unittest.TestCase):
    def test_missing_edp_connector_has_no_guessed_id(self):
        with mock.patch.object(
            main, "find_internal_display_card", return_value=("card0", "eDP-1", "/sys/class/drm/card0-eDP-1")
        ), mock.patch.object(main, "run", return_value={"ok": True, "rc": 0, "out": "", "err": ""}):
            result = main.find_internal_edp_connector_id()

        self.assertFalse(result["ok"])
        self.assertIsNone(result["connector_id"])


class DeckyApiContractTests(unittest.TestCase):
    def test_api_v1_instantiates_plugin_and_binds_native_rpc_arguments(self):
        manifest = json.loads((Path(__file__).parents[1] / "plugin.json").read_text())
        self.assertEqual(manifest["api_version"], 1)
        self.assertIn("root", manifest["flags"])

        plugin = main.Plugin()
        registry = (Path(__file__).parents[1] / "src" / "backend.ts").read_text()
        routes = re.findall(r"^  ([a-z][a-z0-9_]+): (noArgs|objectArg)\(", registry, re.MULTILINE)
        self.assertEqual(len(routes), 36)
        for route, adapter in routes:
            method = getattr(plugin, route)
            signature = inspect.signature(method)
            if adapter == "noArgs":
                signature.bind()
            else:
                signature.bind({})

        inspect.signature(plugin.recent_events).bind(10)


class PcieLinkHealthTests(unittest.TestCase):
    SAMPLE = """
pcieport 0000:00:03.1: AER: Correctable error message received from 0000:05:01.0
pcieport 0000:05:01.0: PCIe Bus Error: severity=Correctable, type=Data Link Layer, (Receiver ID)
pcieport 0000:05:01.0:    [ 7] BadDLLP
pcieport 0000:00:03.1: AER: Uncorrectable (Non-Fatal) error message received from 0000:05:02.0
pcieport 0000:05:02.0: PCIe Bus Error: severity=Uncorrectable (Non-Fatal), type=Transaction Layer, (Receiver ID)
pcieport 0000:05:02.0:    [21] ACSViol (First)
xhci_hcd 0000:09:00.0: AER: can't recover (no error_detected callback)
pcieport 0000:05:02.0: AER: device recovery failed
"""

    def test_summary_counts_canonical_events_without_double_counting_aer_headers(self):
        summary = main.summarize_pcie_link_health(
            self.SAMPLE,
            window_minutes=15,
            g1_pci_functions=["0000:05:01.0", "0000:05:02.0", "0000:09:00.0"],
        )

        self.assertEqual(summary["status"], "degraded")
        self.assertEqual(summary["total_aer_events"], 2)
        self.assertEqual(summary["severity_counts"]["correctable"], 1)
        self.assertEqual(summary["severity_counts"]["uncorrectable_non_fatal"], 1)
        self.assertEqual(summary["error_counts"], {"ACSViol": 1, "BadDLLP": 1})
        self.assertEqual(summary["cannot_recover"], 1)
        self.assertEqual(summary["recovery_failures"], 1)
        self.assertEqual(summary["g1_related_records"], 4)
        self.assertEqual(
            [item["pci"] for item in summary["affected_devices"]],
            ["0000:05:01.0", "0000:05:02.0", "0000:09:00.0"],
        )

    def test_empty_kernel_window_reports_healthy(self):
        summary = main.summarize_pcie_link_health("unrelated kernel message", window_minutes=10)

        self.assertEqual(summary["status"], "healthy")
        self.assertEqual(summary["total_aer_events"], 0)
        self.assertEqual(summary["affected_devices"], [])
        self.assertEqual(summary["headline"], "Healthy · 0 AER · 10 min")

    def test_collector_marks_validated_g1_topology_and_uses_read_only_journal_query(self):
        topology = {
            "complete": True,
            "profile": "gpd-g1-rx7600mxt-titan-ridge",
            "root_pci": "0000:04:00.0",
            "pci_functions": [
                {"pci": "0000:05:01.0"},
                {"pci": "0000:05:02.0"},
                {"pci": "0000:09:00.0"},
            ],
        }
        with mock.patch.object(
            main, "run", return_value={"rc": 0, "out": self.SAMPLE, "err": ""}
        ) as run_mock, mock.patch.object(
            main, "_read_egpu_identity", return_value={"pci": "0000:08:00.0"}
        ), mock.patch.object(
            main, "_pci_inventory", return_value=[{"pci": "0000:08:00.0"}]
        ), mock.patch.object(
            main, "_analyze_gpd_g1_topology", return_value=topology
        ):
            result = main.collect_pcie_link_health(15)

        command = run_mock.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/journalctl", "-k", "-b"])
        self.assertNotIn("sudo", command)
        self.assertTrue(result["g1_topology"]["matched"])
        self.assertEqual(result["g1_topology"]["root_pci"], "0000:04:00.0")
        self.assertEqual(result["g1_related_records"], 4)

    def test_collector_fails_closed_when_kernel_journal_is_unavailable(self):
        with mock.patch.object(
            main, "run", return_value={"rc": 1, "out": "", "err": "permission denied"}
        ):
            result = main.collect_pcie_link_health()

        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "unknown")
        self.assertIn("permission denied", result["error"])

    def test_frontend_shows_the_compact_link_health_headline(self):
        frontend = (Path(__file__).parents[1] / "src" / "index.tsx").read_text(encoding="utf-8")

        self.assertIn('label: "Device diagnostics"', frontend)
        self.assertIn('label: "Summary"', frontend)
        self.assertIn('className: "egbDiagnosticSummary"', frontend)
        self.assertIn('fontSize: "11px"', frontend)
        self.assertIn('"PCIe: "', frontend)
        self.assertIn("diagnostics.pcie_link_health.headline", frontend)
        self.assertIn("diagnostics.ram_gib", frontend)


class DiagnosticRedactionTests(unittest.TestCase):
    def test_recursive_redaction_preserves_hardware_identity(self):
        payload = {
            "hostname": "ally-livingroom",
            "tv": {"ip": "192.168.50.22", "mac": "AA:BB:CC:DD:EE:FF"},
            "log": "ally-livingroom connected from /home/ronnie at 10.0.0.8. Version 1.2.3.4.5",
            "gpu": "65:00.0 VGA compatible controller: AMD Device 7480",
        }

        result = main.redact_diagnostic_payload(payload, hostname="ally-livingroom")
        serialized = json.dumps(result)

        self.assertNotIn("ally-livingroom", serialized)
        self.assertNotIn("192.168.50.22", serialized)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", serialized)
        self.assertNotIn("/home/ronnie", serialized)
        self.assertNotIn("10.0.0.8", serialized)
        self.assertIn("1.2.3.4.5", serialized)
        self.assertIn("65:00.0", serialized)
        self.assertIn("7480", serialized)

    def test_collect_diagnostics_redacts_by_default_and_allows_explicit_local_capture(self):
        fake_uname = mock.Mock(nodename="ally-livingroom", release="6.12.1-test")
        command_result = mock.Mock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "plugin.log"
            log_path.write_text(
                "TV 192.168.50.22 at AA:BB:CC:DD:EE:FF user /home/ronnie on ally-livingroom\n"
            )
            with mock.patch.object(main.os, "uname", return_value=fake_uname, create=True), mock.patch(
                "builtins.open", mock.mock_open(read_data="model name : Test CPU\nMemTotal: 1024 kB\n")
            ), mock.patch.object(main.subprocess, "run", return_value=command_result), mock.patch.object(
                main, "LOG_PATH", log_path
            ), mock.patch.object(
                main, "adb_status", return_value={"path": "/home/ronnie/plugin/bin/adb"}
            ), mock.patch.object(
                main,
                "_read_tv_conf",
                return_value={"TV_IP": "192.168.50.22", "TV_MAC": "AA:BB:CC:DD:EE:FF"},
            ):
                safe = main.collect_diagnostics()
                sensitive = main.collect_diagnostics(include_sensitive=True)

        safe_text = json.dumps(safe)
        sensitive_text = json.dumps(sensitive)
        self.assertTrue(safe["redacted"])
        self.assertNotIn("ally-livingroom", safe_text)
        self.assertNotIn("192.168.50.22", safe_text)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", safe_text)
        self.assertNotIn("/home/ronnie", safe_text)
        self.assertFalse(sensitive["redacted"])
        self.assertIn("192.168.50.22", sensitive_text)

    def test_encoded_support_report_contains_only_redacted_payload(self):
        status_payload = {
            "connected": True,
            "egpu": {"pci": "65:00.0", "tv_ip": "192.168.50.22"},
            "gamescope": "ally-livingroom /home/ronnie",
        }
        fake_uname = mock.Mock(nodename="ally-livingroom")
        with mock.patch.object(main, "build_status", return_value=status_payload), mock.patch.object(
            main, "gamescope_session_block", return_value="connect 192.168.50.22"
        ), mock.patch.object(
            main, "tail_text", return_value="AA:BB:CC:DD:EE:FF /home/ronnie"
        ), mock.patch.object(
            main,
            "run",
            return_value={"ok": True, "rc": 0, "out": "host ally-livingroom", "err": ""},
        ), mock.patch.object(
            main, "make_qr_utf8", return_value={"ok": True, "err": "", "qr": ""}
        ), mock.patch.object(main.os, "uname", return_value=fake_uname, create=True):
            result = main.build_support_report()

        encoded = result["encoded_report"].split(".", 1)[1]
        encoded += "=" * (-len(encoded) % 4)
        compact = json.loads(zlib.decompress(base64.urlsafe_b64decode(encoded)))
        serialized = json.dumps({"report": result["report"], "compact": compact})
        self.assertTrue(result["redacted"])
        self.assertNotIn("ally-livingroom", serialized)
        self.assertNotIn("192.168.50.22", serialized)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", serialized)
        self.assertNotIn("/home/ronnie", serialized)
        self.assertIn("65:00.0", serialized)


class RecentEventRedactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_events_are_redacted_before_rpc_return(self):
        journal = (
            "Aug 30 ally-livingroom eGPUBridge: TV 192.168.50.22 "
            "AA:BB:CC:DD:EE:FF /home/ronnie connected\n"
        )
        fake_uname = mock.Mock(nodename="ally-livingroom")
        with mock.patch.object(
            main, "run", return_value={"ok": True, "rc": 0, "out": journal, "err": "", "cmd": []}
        ), mock.patch.object(main.os, "uname", return_value=fake_uname, create=True):
            result = await main.Plugin().recent_events(10)

        serialized = json.dumps(result)
        self.assertNotIn("ally-livingroom", serialized)
        self.assertNotIn("192.168.50.22", serialized)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", serialized)
        self.assertNotIn("/home/ronnie", serialized)


if __name__ == "__main__":
    unittest.main()
