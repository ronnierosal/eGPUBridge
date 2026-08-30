import fs from "node:fs";

const required = [
  "dist/index.js",
  "src/index.tsx",
  "src/backend.ts",
  "main.py",
  "package.json",
  "plugin.json",
  "pnpm-lock.yaml",
  "rollup.config.js",
  "tsconfig.json",
  "bin/gamescope",
  "LICENSE",
  "README.md",
];
const failures = required.filter((path) => !fs.existsSync(path)).map((path) => `Missing required package file: ${path}`);
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));
const pluginJson = JSON.parse(fs.readFileSync("plugin.json", "utf8"));
const version = packageJson.version;

if (packageJson.main !== "dist/index.js") failures.push(`package.json main is ${packageJson.main}`);
if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version)) failures.push(`package.json has invalid version ${version}`);
if (pluginJson.publish?.version !== version) failures.push(`plugin.json version ${pluginJson.publish?.version} != package.json ${version}`);
if (pluginJson.api_version !== 1) failures.push(`plugin.json api_version is ${pluginJson.api_version}, expected 1`);

const releaseTag = process.env.RELEASE_TAG || "";
if (releaseTag && releaseTag !== `v${version}`) {
  failures.push(`release tag ${releaseTag} does not match v${version}`);
}

if (failures.length) {
  for (const failure of failures) console.error(`ERROR: ${failure}`);
  process.exit(1);
}

console.log(`Package layout OK for eGPUBridge ${version}.`);
