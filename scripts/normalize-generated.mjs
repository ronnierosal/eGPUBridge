import fs from "node:fs";

for (const path of ["dist/index.js", "dist/index.js.map"]) {
  const original = fs.readFileSync(path, "utf8");
  const normalized = `${original.replace(/[ \t]+$/gm, "").trimEnd()}\n`;
  if (normalized !== original) fs.writeFileSync(path, normalized, "utf8");
}
