const element = (type, props, ...children) => ({ type, props: props || {}, children });
const component = (props) => element("mock-component", props, props?.children);

globalThis.window = globalThis;
globalThis.SP_REACT = {
  createElement: element,
  useEffect() {},
  useRef(value) { return { current: value }; },
  useState(value) { return [typeof value === "function" ? value() : value, () => {}]; },
};
globalThis.DFL = {
  ButtonItem: component,
  ConfirmModal: component,
  DialogButton: component,
  Focusable: component,
  PanelSection: component,
  PanelSectionRow: component,
  showModal: () => ({ Close() {}, Update() {} }),
};
globalThis.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit = {
  connect() {
    return {
      _version: 2,
      callable: () => async () => ({ ok: true }),
    };
  },
};

const module = await import(new URL(`../dist/index.js?smoke=${Date.now()}`, import.meta.url));
if (typeof module.default !== "function") throw new Error("Native Decky bundle has no default plugin factory");
const plugin = module.default();
if (plugin?.name !== "eGPUBridge") throw new Error(`Unexpected plugin name: ${plugin?.name}`);
for (const field of ["titleView", "content", "icon", "onDismount"]) {
  if (!(field in plugin)) throw new Error(`Native plugin result is missing ${field}`);
}

console.log("Native Decky bundle smoke test OK.");
