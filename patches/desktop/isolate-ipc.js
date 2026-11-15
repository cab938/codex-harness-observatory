"use strict";

// The pinned Desktop bundle otherwise uses shared, hardcoded /tmp socket paths.
// The candidate launcher provides a private, short IPC root for these endpoints.
const fs = require("node:fs");
const path = require("node:path");

const replacements = [
  ['"/tmp/codex-app-tools"', '(process.env.OBSERVATORY_DESKTOP_IPC_ROOT+"/a")'],
  ['"/tmp/codex-browser-use"', '(process.env.OBSERVATORY_DESKTOP_IPC_ROOT+"/b")'],
  ['`/tmp/codex-host-services-${', '`${process.env.OBSERVATORY_DESKTOP_IPC_ROOT}/h-${'],
];

function isolateIpc(extractedDir) {
  const buildDir = path.join(extractedDir, ".vite", "build");
  const files = fs.readdirSync(buildDir).filter(name => name.endsWith(".js"));
  const sources = files.map(name => ({
    path: path.join(buildDir, name),
    source: fs.readFileSync(path.join(buildDir, name), "utf8"),
  }));
  for (const [before] of replacements) {
    const count = sources.reduce((n, file) => n + file.source.split(before).length - 1, 0);
    if (count !== 1) throw new Error(`Expected exactly one Desktop IPC pattern ${before}, found ${count}`);
  }
  const targets = [];
  for (const file of sources) {
    let patched = file.source;
    for (const [before, after] of replacements) patched = patched.replace(before, after);
    if (patched !== file.source) {
      fs.writeFileSync(file.path, patched, "utf8");
      targets.push(path.relative(extractedDir, file.path));
    }
  }
  return { matched: 1, changed: 1, targets };
}

function isolateBundledServices(appDir) {
  const base = path.join(appDir, "resources", "plugins", "openai-bundled", "plugins");
  const services = [
    ...["browser", "chrome"].map(plugin => path.join(base, plugin, "scripts", "browser-service.mjs")),
    path.join(appDir, "resources", "cua_node", "lib", "node_modules", "@oai", "browser-desktop", "scripts", "browser-service.mjs"),
    path.join(appDir, "resources", "cua_node", "lib", "node_modules", "@oai", "cua", "dist", "lib", "js", "oai_js_browser", "dist", "skill", "scripts", "browser-service.mjs"),
  ];
  for (const file of services) {
    const source = fs.readFileSync(file, "utf8");
    const before = '"/tmp/codex-browser-use"';
    if (source.split(before).length !== 2) {
      throw new Error(`Expected one browser IPC pattern in ${file}`);
    }
    // Core's local MCP launcher forwards HOME by default and the CUA config
    // explicitly supplies CODEX_HOME, but drops arbitrary custom env vars.
    // Accept HOME only when it is exactly this candidate's private runtime.
    const root = '(process.env.OBSERVATORY_DESKTOP_IPC_ROOT||(process.env.CODEX_HOME&&process.env.HOME===process.env.CODEX_HOME+"/.obs/r"?process.env.HOME:(()=>{throw Error("Observatory IPC root missing")})()))';
    fs.writeFileSync(file, source.replace(before, `(${root}+"/b")`), "utf8");
  }
  // This optional native Chrome extension host has a compiled-in shared /tmp
  // path and offers no environment override. Keep it present but non-executable.
  const nativeHost = path.join(base, "chrome", "extension-host", "linux", "x64", "extension-host");
  fs.chmodSync(nativeHost, fs.statSync(nativeHost).mode & ~0o111);
}

function guardLauncher(appDir) {
  const file = path.join(appDir, "start.sh");
  const source = fs.readFileSync(file, "utf8");
  if (!source.startsWith("#!/bin/bash\n") || source.includes("OBSERVATORY_LAUNCH_GUARD")) {
    throw new Error("Unexpected candidate launcher; refusing to build without its isolation guard");
  }
  const guard = `# OBSERVATORY_LAUNCH_GUARD: start through the Observatory isolation launcher.
if [[ "\${OBSERVATORY_DESKTOP_LAUNCH:-}" != 1 || -z "\${OBSERVATORY_CODEX_HOME:-}" ||
      "\${CODEX_HOME:-}" != "$OBSERVATORY_CODEX_HOME" || "$CODEX_HOME" != /* ||
      ! -d "$CODEX_HOME" || -L "$CODEX_HOME" ||
      "$(realpath -e -- "$CODEX_HOME")" != "$CODEX_HOME" ||
      "$(stat -c %u -- "$CODEX_HOME")" != "$(id -u)" ||
      "\${HOME:-}" != "$CODEX_HOME/.obs/r" || "\${XDG_RUNTIME_DIR:-}" != "$HOME" ||
      "\${OBSERVATORY_DESKTOP_IPC_ROOT:-}" != "$HOME" ||
      "\${CODEX_ELECTRON_USER_DATA_PATH:-}" != "$CODEX_HOME/.obs/electron" ||
      "\${CODEX_LINUX_APP_ID:-}" != codex-observatory-0-3 ]]; then
  echo "Start this isolated candidate through the Observatory launcher with a dedicated OBSERVATORY_CODEX_HOME." >&2
  exit 1
fi
mode="$(stat -c %a -- "$CODEX_HOME")"
if (( (8#$mode & 8#077) != 0 )); then
  echo "OBSERVATORY_CODEX_HOME must be private (0700)." >&2
  exit 1
fi
`;
  fs.writeFileSync(file, source.replace("#!/bin/bash\n", `#!/bin/bash\n${guard}`), "utf8");
}

module.exports = {
  guardLauncher,
  isolateBundledServices,
  descriptors: [{
    id: "observatory-private-ipc-paths",
    phase: "extracted-app:pre-webview",
    order: 141,
    ciPolicy: "required-upstream",
    apply: isolateIpc,
    status: () => "applied",
  }],
  isolateIpc,
};
