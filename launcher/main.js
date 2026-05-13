const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

// Resolve install root (parent of launcher/)
const INSTALL_ROOT = path.resolve(__dirname, '..');
const CONFIG_PATH = path.join(INSTALL_ROOT, 'config', 'jarvis.json');

let mainWindow = null;
let backendProcess = null;
let config = {};

// Load config
function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    }
  } catch (e) {
    config = { backend_port: 8000 };
  }
  return config;
}

// Start FastAPI backend
function startBackend() {
  const backendScript = path.join(INSTALL_ROOT, 'scripts', 'start_backend.py');
  const pythonExe = path.join(INSTALL_ROOT, 'venv', 'Scripts', 'python.exe');
  const python = fs.existsSync(pythonExe) ? pythonExe : 'python';

  backendProcess = spawn(python, [backendScript], {
    cwd: INSTALL_ROOT,
    env: {
      ...process.env,
      JARVIS_ROOT: INSTALL_ROOT,
      PYTHONUNBUFFERED: '1'
    },
    detached: false
  });

  backendProcess.stdout.on('data', (d) => console.log('[backend]', d.toString()));
  backendProcess.stderr.on('data', (d) => console.error('[backend]', d.toString()));
  backendProcess.on('exit', (code) => console.log('[backend] exited:', code));
}

// Create main window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    frame: false,           // Custom titlebar
    transparent: false,
    backgroundColor: '#020408',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true
    },
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    show: false             // Show after ready-to-show
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Open external links in browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

// IPC handlers
ipcMain.on('window:minimize', () => mainWindow?.minimize());
ipcMain.on('window:maximize', () => {
  mainWindow?.isMaximized() ? mainWindow.unmaximize() : mainWindow?.maximize();
});
ipcMain.on('window:close', () => {
  app.quit();
});
ipcMain.handle('get:config', () => config);
ipcMain.handle('get:install-root', () => INSTALL_ROOT);

// App lifecycle
app.whenReady().then(() => {
  loadConfig();
  startBackend();

  // Small delay to let backend start
  setTimeout(createWindow, 1500);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (backendProcess) backendProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (backendProcess) backendProcess.kill();
});
