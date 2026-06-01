/**
 * WeatherFlow Desktop — Electron main process.
 *
 * Creates a transparent, borderless, always-on-top window with a draggable
 * character. System tray icon for quick access.
 *
 * Per weatherflow-architecture-v2.md §14 + Phase 2.
 */

import { app, BrowserWindow, Tray, Menu, screen, ipcMain } from "electron";
import * as path from "path";

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;

const WINDOW_WIDTH = 200;
const WINDOW_HEIGHT = 250;

function createWindow(): void {
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    x: screenW - WINDOW_WIDTH - 20,
    y: screenH - WINDOW_HEIGHT - 20,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadFile(path.join(__dirname, "..", "src", "renderer", "index.html"));
  mainWindow.setVisibleOnAllWorkspaces(true);

  // Make window draggable via CSS (-webkit-app-region: drag)
  mainWindow.setIgnoreMouseEvents(false);
}

function createTray(): void {
  // Use a simple icon; in production, use a proper .png/.ico
  tray = new Tray(path.join(__dirname, "..", "assets", "tray-icon.png"));

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Show/Hide",
      click: () => {
        if (mainWindow) {
          mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
        }
      },
    },
    {
      label: "Open Chat",
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.webContents.send("open-chat");
        }
      },
    },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        app.quit();
      },
    },
  ]);

  tray.setToolTip("WeatherFlow — Rhythm Companion");
  tray.setContextMenu(contextMenu);

  tray.on("click", () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    }
  });
}

// IPC: receive hypothesis updates from renderer
ipcMain.on("hypothesis-update", (_event, data) => {
  console.log("Hypothesis update:", data);
});

// IPC: toggle chat panel
ipcMain.on("toggle-chat", (_event, show: boolean) => {
  if (mainWindow) {
    if (show) {
      mainWindow.setSize(WINDOW_WIDTH, 500);
    } else {
      mainWindow.setSize(WINDOW_WIDTH, WINDOW_HEIGHT);
    }
  }
});

app.whenReady().then(() => {
  createWindow();
  createTray();
});

app.on("window-all-closed", () => {
  // Keep running in tray on macOS
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
