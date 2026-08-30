import fs from "node:fs";

const bundlePath = "dist/index.js";
const bundle = fs.readFileSync(bundlePath, "utf8");
const normalizedBundle = `${bundle.replace(/[ \t]+$/gm, "").trimEnd()}\n`;
if (normalizedBundle !== bundle) fs.writeFileSync(bundlePath, normalizedBundle, "utf8");
