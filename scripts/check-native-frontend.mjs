import fs from "node:fs";

const source = fs.readFileSync("src/index.tsx", "utf8");
const backend = fs.readFileSync("src/backend.ts", "utf8");
const bundle = fs.readFileSync("dist/index.js", "utf8");
const manifest = JSON.parse(fs.readFileSync("plugin.json", "utf8"));

const failures = [];
const routePattern = /^  ([a-z][a-z0-9_]+):/gm;
const registeredRoutes = new Set(Array.from(backend.matchAll(routePattern), (match) => match[1]));
const usedRoutePattern = /\b(?:call|doCall)\(\s*(?:serverApi\s*,\s*)?["']([a-z][a-z0-9_]+)["']/g;
const usedRoutes = new Set(Array.from(source.matchAll(usedRoutePattern), (match) => match[1]));
const missingRoutes = Array.from(usedRoutes).filter((route) => !registeredRoutes.has(route)).sort();

if (missingRoutes.length) {
  failures.push(`Frontend routes missing from typed registry: ${missingRoutes.join(", ")}`);
}
if (manifest.api_version !== 1) {
  failures.push(`plugin.json api_version must be 1, found ${manifest.api_version}`);
}
if (!Array.isArray(manifest.flags) || !manifest.flags.includes("root")) {
  failures.push("plugin.json must retain the root flag for hardware operations");
}
if (source.includes("callPluginMethod") || bundle.includes("callPluginMethod")) {
  failures.push("Legacy serverApi.callPluginMethod remains in the native frontend");
}
if (source.includes("window.eGPUBridgePlugin") || bundle.includes("window.eGPUBridgePlugin")) {
  failures.push("Legacy window.eGPUBridgePlugin registration remains in the native frontend");
}
if (!bundle.includes("__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit")) {
  failures.push("Generated bundle does not contain the @decky/api loader connection");
}
if (!bundle.includes("export { index as default }")) {
  failures.push("Generated bundle does not expose the native default plugin export");
}
if (!source.includes("confirmExternalDisplayHandoff") || !source.includes("ConfirmModal")) {
  failures.push("External display switching must retain native TV-input confirmation");
}
if (source.includes('"ASMedia 246x \\u00b7 "')) {
  failures.push("Dock summary still hard-codes the bridge name instead of the detected GPU model");
}
if (source.includes("toaster.toast")) {
  failures.push("Display handoff still depends on a toast that failed Ally visual validation");
}

if (failures.length) {
  for (const failure of failures) console.error(`ERROR: ${failure}`);
  process.exit(1);
}

console.log(`Native Decky frontend contract OK (${registeredRoutes.size} registered RPC routes).`);
