import { callable } from "@decky/api";

export type RpcResult = Record<string, unknown> & {
  ok?: boolean;
  error?: string;
};

export type RpcArgs = Record<string, unknown>;

type RpcInvoker = (args?: RpcArgs) => Promise<RpcResult>;

const noArgs = (route: string): RpcInvoker => {
  const invoke = callable<[], RpcResult>(route);
  return () => invoke();
};

const objectArg = (route: string): RpcInvoker => {
  const invoke = callable<[args: RpcArgs], RpcResult>(route);
  return (args = {}) => invoke(args);
};

const recentEventsCall = callable<[minutes: number], RpcResult>("recent_events");

export const backendRpc = {
  adb_status: noArgs("adb_status"),
  amd_sysfs_wagon: noArgs("amd_sysfs_wagon"),
  apply_egpu_mode: objectArg("apply_egpu_mode"),
  collect_diagnostics: noArgs("collect_diagnostics"),
  dock_status: noArgs("dock_status"),
  get_hotkey_settings: noArgs("get_hotkey_settings"),
  get_tv_automation_settings: noArgs("get_tv_automation_settings"),
  get_tv_ip: noArgs("get_tv_ip"),
  gpu_get_od_clocks: noArgs("gpu_get_od_clocks"),
  gpu_set_fan_control: objectArg("gpu_set_fan_control"),
  gpu_set_od_clocks: objectArg("gpu_set_od_clocks"),
  gpu_set_perf_level: objectArg("gpu_set_perf_level"),
  gpu_set_power_cap: objectArg("gpu_set_power_cap"),
  gpu_set_power_profile: objectArg("gpu_set_power_profile"),
  gpu_tuning_wagon: noArgs("gpu_tuning_wagon"),
  install_adb: noArgs("install_adb"),
  nvidia_activate: noArgs("nvidia_activate"),
  nvidia_deactivate: noArgs("nvidia_deactivate"),
  nvidia_install_driver: noArgs("nvidia_install_driver"),
  nvidia_uninstall_driver: noArgs("nvidia_uninstall_driver"),
  prepare_for_unplug: noArgs("prepare_for_unplug"),
  recent_events: (args: RpcArgs = {}) => recentEventsCall(Number(args.minutes ?? 10)),
  restore_internal_mode: objectArg("restore_internal_mode"),
  safe_disconnect: noArgs("safe_disconnect"),
  save_tv_ip: objectArg("save_tv_ip"),
  set_hotkey_settings: objectArg("set_hotkey_settings"),
  set_tv_automation_settings: objectArg("set_tv_automation_settings"),
  smart_toggle_display: objectArg("smart_toggle_display"),
  status: noArgs("status"),
  tv_control_health: noArgs("tv_control_health"),
  tv_input: noArgs("tv_input"),
  tv_input_mode: objectArg("tv_input_mode"),
  tv_off: noArgs("tv_off"),
  tv_on: noArgs("tv_on"),
  tv_power_light: noArgs("tv_power_light"),
} satisfies Record<string, RpcInvoker>;

export type BackendRoute = keyof typeof backendRpc;

export function callBackend(route: BackendRoute, args: RpcArgs = {}): Promise<RpcResult> {
  return backendRpc[route](args);
}
