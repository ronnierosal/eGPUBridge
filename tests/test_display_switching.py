import unittest
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


if __name__ == "__main__":
    unittest.main()
