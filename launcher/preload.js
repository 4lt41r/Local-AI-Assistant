const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
  // Window controls
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close:    () => ipcRenderer.send('window:close'),

  // Config
  getConfig:      () => ipcRenderer.invoke('get:config'),
  getInstallRoot: () => ipcRenderer.invoke('get:install-root'),
});
