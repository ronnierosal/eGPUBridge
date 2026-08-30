import fs from "node:fs";

const bundlePath = "dist/index.js";
const bundle = fs.readFileSync(bundlePath, "utf8");
const normalizedBundle = `${bundle.replace(/[ \t]+$/gm, "").trimEnd()}\n`;
if (normalizedBundle !== bundle) fs.writeFileSync(bundlePath, normalizedBundle, "utf8");

const mapPath = "dist/index.js.map";
const sourceMap = JSON.parse(fs.readFileSync(mapPath, "utf8"));
sourceMap.sourcesContent = (sourceMap.sourcesContent || []).map((content) =>
  typeof content === "string" ? content.replace(/\r\n?/g, "\n") : content,
);
fs.writeFileSync(mapPath, `${JSON.stringify(sourceMap)}\n`, "utf8");
