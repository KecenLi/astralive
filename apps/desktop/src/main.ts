import { app, BrowserWindow, desktopCapturer, ipcMain, screen, session } from "electron";
import { spawn, ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";

interface DesktopSettings {
  firstRunComplete?: boolean;
  autostartAsked?: boolean;
  autostartEnabled?: boolean;
  captureMode?: "low_fps" | "continuous";
  petEnabled?: boolean;
}

let mainWindow: BrowserWindow | null = null;
let petWindow: BrowserWindow | null = null;
let backendProcess: ChildProcessWithoutNullStreams | null = null;
let backendUrl = "";
let backendError = "";

const remoteDebugArg = process.argv.find((arg) => arg.startsWith("--remote-debugging-port="));
const remoteDebugPort =
  process.env.MODVII_REMOTE_DEBUGGING_PORT || remoteDebugArg?.split("=", 2)[1] || "";
if (remoteDebugPort) {
  app.commandLine.appendSwitch("remote-debugging-port", remoteDebugPort);
}

if (process.env.MODVII_FAKE_MEDIA === "1") {
  app.commandLine.appendSwitch("use-fake-ui-for-media-stream");
  app.commandLine.appendSwitch("use-fake-device-for-media-stream");
  if (process.env.MODVII_FAKE_AUDIO_PATH) {
    app.commandLine.appendSwitch("use-file-for-fake-audio-capture", process.env.MODVII_FAKE_AUDIO_PATH);
  }
}

const userDataDir = process.env.MODVII_USER_DATA_DIR;
if (userDataDir) {
  app.setPath("userData", userDataDir);
}

function log(message: string, detail?: unknown) {
  try {
    const baseDir = app.isReady()
      ? app.getPath("userData")
      : path.join(process.env.TEMP || process.cwd(), "MODVII");
    fs.mkdirSync(baseDir, { recursive: true });
    const line = `[${new Date().toISOString()}] ${message}${
      detail === undefined ? "" : ` ${detail instanceof Error ? detail.stack || detail.message : JSON.stringify(detail)}`
    }\n`;
    fs.appendFileSync(path.join(baseDir, "desktop.log"), line, "utf8");
  } catch {
    // File logging must never break app startup.
  }
}

function repoRoot() {
  return path.resolve(__dirname, "../../..");
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function readSettings(): DesktopSettings {
  try {
    return JSON.parse(fs.readFileSync(settingsPath(), "utf8")) as DesktopSettings;
  } catch {
    return {};
  }
}

function parseDotenv(filePath: string): Record<string, string> {
  const result: Record<string, string> = {};
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line);
    if (!match) continue;

    let value = match[2].trim();
    const quote = value[0];
    if ((quote === "\"" || quote === "'") && value.endsWith(quote)) {
      value = value.slice(1, -1);
      if (quote === "\"") {
        value = value
          .replace(/\\n/g, "\n")
          .replace(/\\r/g, "\r")
          .replace(/\\t/g, "\t")
          .replace(/\\"/g, "\"")
          .replace(/\\\\/g, "\\");
      }
    } else {
      value = value.replace(/\s+#.*$/, "").trim();
    }
    result[match[1]] = value;
  }
  return result;
}

function addDotenvCandidates(candidates: string[], startDir?: string, maxDepth = 5) {
  if (!startDir) return;
  let current = path.resolve(startDir);
  for (let depth = 0; depth < maxDepth; depth += 1) {
    candidates.push(path.join(current, ".env"));
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
}

function findDotenvFile() {
  const candidates: string[] = [];
  if (process.env.MODVII_ENV_FILE) {
    candidates.push(process.env.MODVII_ENV_FILE);
  }
  addDotenvCandidates(candidates, process.env.PORTABLE_EXECUTABLE_DIR);
  addDotenvCandidates(candidates, path.dirname(process.execPath));
  addDotenvCandidates(candidates, process.cwd());
  addDotenvCandidates(candidates, app.getPath("userData"), 2);
  if (!app.isPackaged) {
    addDotenvCandidates(candidates, repoRoot(), 1);
  }

  const seen = new Set<string>();
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (seen.has(resolved)) continue;
    seen.add(resolved);
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
      return resolved;
    }
  }
  return "";
}

function writeSettings(patch: Partial<DesktopSettings>): DesktopSettings {
  const next = { ...readSettings(), ...patch };
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(next, null, 2), "utf8");
  return next;
}

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (address && typeof address === "object") resolve(address.port);
        else reject(new Error("Could not allocate a local port."));
      });
    });
  });
}

function waitForHealth(url: string, timeoutMs = 30_000): Promise<void> {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const probe = () => {
      const req = http.get(`${url}/health`, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          resolve();
          return;
        }
        retry();
      });
      req.on("error", retry);
      req.setTimeout(1500, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error(`MODVII backend did not become ready at ${url}.`));
        return;
      }
      setTimeout(probe, 500);
    };
    probe();
  });
}

async function startBackend() {
  const port = await findFreePort();
  backendUrl = `http://127.0.0.1:${port}`;
  backendError = "";
  const dataDir = path.join(app.getPath("userData"), "data");
  const dotenvFile = findDotenvFile();
  const dotenvEnv = dotenvFile ? parseDotenv(dotenvFile) : {};
  log("Backend dotenv resolved", { dotenvFile: dotenvFile || undefined });
  const env = {
    ...dotenvEnv,
    ...process.env,
    APP_NAME: "MODVII",
    WAKE_WORD: "小七",
    SERVER_HOST: "127.0.0.1",
    SERVER_PORT: String(port),
    WEB_ORIGIN: "file://",
    DATA_DIR: dataDir,
    GOOGLE_CLOUD_PROJECT:
      process.env.GOOGLE_CLOUD_PROJECT ||
      dotenvEnv.GOOGLE_CLOUD_PROJECT ||
      process.env.VERTEX_AI_PROJECT ||
      dotenvEnv.VERTEX_AI_PROJECT ||
      "",
  };

  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, "server", "modvii-server.exe");
    log("Starting packaged backend", { executable, backendUrl });
    backendProcess = spawn(executable, [], { env, windowsHide: true });
  } else {
    const serverDir = path.join(repoRoot(), "apps", "server");
    const uvCommand = process.platform === "win32" ? "uv.exe" : "uv";
    log("Starting development backend", { serverDir, uvCommand, backendUrl });
    backendProcess = spawn(
      uvCommand,
      ["run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)],
      { cwd: serverDir, env, windowsHide: true },
    );
  }

  backendProcess.once("error", (error) => {
    backendError = error.message;
    log("Backend process error", error);
  });
  backendProcess.stderr.on("data", (chunk) => {
    const text = String(chunk).trim();
    if (text) {
      backendError = text;
      log("Backend stderr", text);
    }
  });

  await waitForHealth(backendUrl);
  log("Backend health ready", { backendUrl });
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) return;
  const pid = backendProcess.pid;
  if (process.platform === "win32" && pid) {
    spawn("taskkill.exe", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
  } else {
    backendProcess.kill("SIGTERM");
  }
  backendProcess = null;
}

function configurePermissions() {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission === "media" || permission === "display-capture");
  });
}

async function createWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    return mainWindow;
  }

  log("Creating window", { packaged: app.isPackaged, resourcesPath: process.resourcesPath });
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 680,
    title: "MODVII",
    backgroundColor: "#edf0eb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.webContents.on("did-fail-load", (_event, code, description, validatedUrl) => {
    log("Renderer load failed", { code, description, validatedUrl });
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    log("Renderer process gone", details);
  });
  mainWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      log("Renderer console", { level, message, line, sourceId });
    }
  });
  mainWindow.webContents.once("did-finish-load", () => {
    void writeRendererSmokeReport();
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  await loadRenderer(mainWindow, "main");
  return mainWindow;
}

async function loadRenderer(target: BrowserWindow, mode: "main" | "pet") {
  const rendererUrl = process.env.MODVII_RENDERER_URL;
  const query = new URLSearchParams({ apiBaseUrl: backendUrl, mode });
  if (!app.isPackaged && rendererUrl) {
    const separator = rendererUrl.includes("?") ? "&" : "?";
    await target.loadURL(`${rendererUrl}${separator}${query.toString()}`);
    log("Loaded renderer URL", { rendererUrl, mode });
    return;
  }

  const indexPath = app.isPackaged
    ? path.join(process.resourcesPath, "web", "index.html")
    : path.join(repoRoot(), "apps", "web", "dist", "index.html");
  await target.loadFile(indexPath, { query: { apiBaseUrl: backendUrl, mode } });
  log("Loaded renderer file", { indexPath, mode });
}

async function createPetWindow() {
  if (petWindow && !petWindow.isDestroyed()) {
    petWindow.show();
    petWindow.focus();
    return petWindow;
  }

  const area = screen.getPrimaryDisplay().workArea;
  const width = 340;
  const height = 500;
  petWindow = new BrowserWindow({
    width,
    height,
    x: Math.max(area.x, area.x + area.width - width - 24),
    y: Math.max(area.y, area.y + area.height - height - 24),
    minWidth: 260,
    minHeight: 360,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: true,
    hasShadow: false,
    backgroundColor: "#00000000",
    title: "MODVII Pet",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  petWindow.setAlwaysOnTop(true, "floating");
  petWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  petWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      log("Pet renderer console", { level, message, line, sourceId });
    }
  });
  petWindow.on("closed", () => {
    petWindow = null;
  });
  await loadRenderer(petWindow, "pet");
  writeSettings({ petEnabled: true });
  return petWindow;
}

async function writeRendererSmokeReport() {
  const reportPath = process.env.MODVII_RENDERER_SMOKE_PATH;
  if (!reportPath || !mainWindow) return;

  try {
    const report = await mainWindow.webContents.executeJavaScript(`
      new Promise((resolve) => {
        setTimeout(() => {
          const root = document.querySelector("#root");
          resolve({
            href: window.location.href,
            title: document.title,
            rootChildren: root ? root.childElementCount : -1,
            bodyText: document.body.innerText.slice(0, 1000),
            scripts: Array.from(document.scripts).map((script) => script.src),
            stylesheets: Array.from(document.styleSheets).length
          });
        }, 1200);
      })
    `);
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
    log("Renderer smoke report written", reportPath);
  } catch (error) {
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(
      reportPath,
      JSON.stringify({ error: error instanceof Error ? error.message : String(error) }, null, 2),
      "utf8",
    );
    log("Renderer smoke report failed", error);
  } finally {
    app.quit();
  }
}

function registerIpc() {
  ipcMain.handle("runtime:getBackendUrl", () => backendUrl);
  ipcMain.handle("runtime:getBackendStatus", () => ({
    ready: Boolean(backendUrl && !backendError),
    url: backendUrl,
    error: backendError || undefined,
  }));
  ipcMain.handle("screen:getPrimarySource", async () => {
    const sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: { width: 0, height: 0 },
    });
    const source = sources[0];
    if (!source) throw new Error("No screen source is available.");
    return { id: source.id, name: source.name };
  });
  ipcMain.handle("autostart:get", () => app.getLoginItemSettings().openAtLogin);
  ipcMain.handle("autostart:set", (_event, enabled: boolean) => {
    app.setLoginItemSettings({ openAtLogin: enabled });
    writeSettings({ autostartEnabled: enabled, autostartAsked: true });
    return app.getLoginItemSettings().openAtLogin;
  });
  ipcMain.handle("settings:get", () => readSettings());
  ipcMain.handle("settings:set", (_event, patch: Partial<DesktopSettings>) => writeSettings(patch));
  ipcMain.handle("pet:getState", () => ({ visible: Boolean(petWindow && !petWindow.isDestroyed() && petWindow.isVisible()) }));
  ipcMain.handle("pet:show", async () => {
    await createPetWindow();
    writeSettings({ petEnabled: true });
    return { visible: true };
  });
  ipcMain.handle("pet:hide", () => {
    petWindow?.hide();
    writeSettings({ petEnabled: false });
    return { visible: false };
  });
  ipcMain.handle("pet:toggle", async () => {
    if (petWindow && !petWindow.isDestroyed() && petWindow.isVisible()) {
      petWindow.hide();
      writeSettings({ petEnabled: false });
      return { visible: false };
    }
    await createPetWindow();
    writeSettings({ petEnabled: true });
    return { visible: true };
  });
}

const gotLock = app.requestSingleInstanceLock();
log("Main module loaded", { gotLock });
if (!gotLock) {
  log("Single instance lock unavailable; quitting.");
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      mainWindow = null;
      void createWindow().catch((error) => log("Second-instance window restore failed", error));
      return;
    }
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    log("App ready", {
      packaged: app.isPackaged,
      version: app.getVersion(),
      remoteDebugPort: remoteDebugPort || app.commandLine.getSwitchValue("remote-debugging-port") || "",
    });
    registerIpc();
    configurePermissions();
    try {
      await startBackend();
    } catch (error) {
      backendError = error instanceof Error ? error.message : String(error);
      log("Backend startup failed", error);
    }
    await createWindow();
    if (!process.env.MODVII_RENDERER_SMOKE_PATH && readSettings().petEnabled !== false) {
      await createPetWindow();
    }
  }).catch((error) => {
    log("App startup failed", error);
    app.quit();
  });
}

app.on("window-all-closed", () => {
  log("All windows closed; quitting.");
  mainWindow = null;
  petWindow = null;
  stopBackend();
  app.quit();
});

app.on("before-quit", stopBackend);

process.on("uncaughtException", (error) => {
  log("Uncaught exception", error);
});

process.on("unhandledRejection", (reason) => {
  log("Unhandled rejection", reason);
});
