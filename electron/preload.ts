/**
 * Electron Preload 脚本
 * 安全地暴露主进程 API 给渲染进程
 */
import { contextBridge, ipcRenderer } from 'electron';

/** 暴露给前端的 API 接口 */
const electronAPI = {
  /** 获取 Python 后端端口号 */
  getBackendPort: (): Promise<number> => ipcRenderer.invoke('get-backend-port'),

  /** 获取后端运行状态 */
  getBackendStatus: (): Promise<boolean> => ipcRenderer.invoke('get-backend-status'),

  /** 平台信息 */
  platform: process.platform,
};

// 通过 contextBridge 安全暴露 API
contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// TypeScript 类型声明
export type ElectronAPI = typeof electronAPI;

