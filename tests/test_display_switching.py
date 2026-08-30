import unittest
import tempfile
import inspect
import json
import re
import base64
import zlib
from pathlib import Path
from unittest import mock

import main


def status(*, connector="HDMI-A-1", output_order="", gamescope=""):
    return {
        "egpu": {"card": "card1"},
        "recommended_connector": {"name": connector, "status": "connected"},
        "patch_state": {"output_order": output_order},
        "gamescope": gamescope,
    }


class DisplayTargetTests(unittest.TestCase):
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


class SystemCommandTests(unittest.TestCase):
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
        self.assertEqual(len(routes), 34)
        for route, adapter in routes:
            method = getattr(plugin, route)
            signature = inspect.signature(method)
            if adapter == "noArgs":
                signature.bind()
            else:
                signature.bind({})

        inspect.signature(plugin.recent_events).bind(10)


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
