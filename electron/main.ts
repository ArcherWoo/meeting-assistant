/**
 * Electron 主进程入口
 * 负责：创建窗口、启动 Python 后端、IPC 通信
 */
import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'path';
import { PythonManager } from './python-manager';

// 禁用 Electron 安全警告（开发环境）
process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = 'true';

let mainWindow: BrowserWindow | null = null;
const pythonManager = new PythonManager();

/** 创建主窗口 */
function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    titleBarStyle: 'hiddenInset', // macOS 红绿灯样式
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false, // 等待 ready-to-show 再显示，避免白屏闪烁
  });

  // 开发环境加载 Vite dev server，生产环境加载打包文件
  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  // 窗口准备好后再显示，提升启动体验
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/** 注册 IPC 通信处理器 */
function registerIpcHandlers(): void {
  // 获取后端服务端口
  ipcMain.handle('get-backend-port', () => {
    return pythonManager.getPort();
  });

  // 获取后端服务状态
  ipcMain.handle('get-backend-status', () => {
    return pythonManager.isRunning();
  });
}

// ===== 应用生命周期 =====

app.whenReady().then(async () => {
  registerIpcHandlers();

  // 启动 Python FastAPI 后端
  try {
    await pythonManager.start();
    console.log(`[Main] Python backend started on port ${pythonManager.getPort()}`);
  } catch (error) {
    console.error('[Main] Failed to start Python backend:', error);
    // 后端启动失败不阻塞前端，前端会显示连接状态
  }

  createWindow();

  // macOS: 点击 dock 图标时重新创建窗口
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// 所有窗口关闭时退出应用（macOS 除外）
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// 应用退出前关闭 Python 后端
app.on('before-quit', async () => {
  await pythonManager.stop();
});

