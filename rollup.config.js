import deckyPlugin from "@decky/rollup";

const config = deckyPlugin({});

// Source maps embed platform-specific compiler mappings. The runtime bundle is
// the release artifact and must remain byte-reproducible across Windows/Linux.
config.output = { ...config.output, sourcemap: false };

export default config;
