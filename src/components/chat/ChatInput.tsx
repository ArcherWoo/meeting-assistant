/**
 * 聊天输入组件
 * 自动扩展的文本输入框 + 附件上传（提取文本作为上下文） + 发送/停止按钮
 */
import { useState, useRef, useCallback, useEffect, type KeyboardEvent, type ChangeEvent } from 'react';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import { extractFilesText } from '@/services/api';

/** 附件信息 */
interface Attachment {
  id: string;
  filename: string;
  fileType: string;
  fileSize: number;
  text: string;
  charCount: number;
}

interface Props {
  /** 发送消息（content + 可选附件文本上下文） */
  onSend: (content: string, attachmentContext?: string) => Promise<void> | void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  /** 外部预填充文本（如 Skill 推荐），设置后自动写入输入框 */
  prefillText?: string;
  /** 预填充文本消费后的清除回调 */
  onPrefillConsumed?: () => void;
}

export default function ChatInput({ onSend, onStop, isStreaming, disabled, prefillText, onPrefillConsumed }: Props) {
  const { llmConfigs, activeLLMConfigId, setActiveLLMConfig, toggleSettings } = useAppStore();
  const [input, setInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeLLMConfig = llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0];

  // 外部预填充文本写入输入框
  useEffect(() => {
    if (prefillText) {
      setInput(prefillText);
      onPrefillConsumed?.();
      // 聚焦输入框
      setTimeout(() => textareaRef.current?.focus(), 0);
    }
  }, [prefillText, onPrefillConsumed]);

  /** 触发文件选择 */
  const triggerFileUpload = () => fileInputRef.current?.click();

  /** 处理文件选择 → 提取文本作为附件 */
  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    e.target.value = '';

    setUploading(true);
    try {
      const result = await extractFilesText(files);
      const fileSizeQueue = files.reduce<Record<string, number[]>>((acc, file) => {
        if (!acc[file.name]) {
          acc[file.name] = [];
        }
        acc[file.name].push(file.size);
        return acc;
      }, {});
      const nextAttachments = result.files.map((item, index) => ({
        id: globalThis.crypto?.randomUUID?.() ?? `${item.filename}-${index}-${Date.now()}-${Math.random()}`,
        filename: item.filename,
        fileType: item.file_type,
        fileSize: fileSizeQueue[item.filename]?.shift() ?? 0,
        text: item.text,
        charCount: item.char_count,
      }));
      const failedMessages = result.errors.map((item) => `${item.filename}: ${item.error}`);

      if (nextAttachments.length > 0) {
        setAttachments((current) => [...current, ...nextAttachments]);
      }
      if (failedMessages.length > 0) {
        alert(`以下文件文本提取失败：\n${failedMessages.join('\n')}`);
      }
    } catch (err: any) {
      alert(`文件文本提取失败：${err.message || '未知错误'}`);
    } finally {
      setUploading(false);
    }
  };

  /** 移除附件 */
  const removeAttachment = (id: string) => {
    setAttachments((current) => current.filter((attachment) => attachment.id !== id));
  };

  /** 格式化文件大小 */
  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  /** 自动调整高度（最大 200px） */
  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  }, []);

  /** 发送消息（附件文本作为上下文一起发送） */
  const handleSend = () => {
    const trimmed = input.trim();
    // 允许只有附件没有文字（此时用默认提示词）
    if (!trimmed && attachments.length === 0) return;
    if (isStreaming) return;

    const userMessage = trimmed || (attachments.length > 1 ? '请综合分析这些文件的内容' : '请分析这份文件的内容');
    const attachmentContext = attachments.length > 0
      ? attachments.map((attachment, index) => (
          `\n\n---\n📎 附件${attachments.length > 1 ? ` #${index + 1}` : ''}「${attachment.filename}」内容（${attachment.charCount} 字符）：\n\n${attachment.text}`
        )).join('')
      : undefined;

    void Promise.resolve(onSend(userMessage, attachmentContext)).catch((error: unknown) => {
      alert((error as Error).message || '发送失败');
    });
    setInput('');
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  /** 键盘事件：Enter 发送，Shift+Enter 换行 */
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = Boolean(input.trim() || attachments.length > 0) && !disabled;

  return (
    <div className="border-t border-surface-divider dark:border-dark-divider bg-surface-card dark:bg-dark-card px-4 py-3">
      {/* API Key 未配置提示 */}
      {disabled && (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-amber-100 text-[11px] dark:bg-amber-900/40">⚠</span>
          <span>请先在设置中配置 API Key</span>
        </div>
      )}

      {/* 附件预览 */}
      {attachments.length > 0 && (
        <div className="mb-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 shadow-sm dark:border-blue-800 dark:bg-blue-900/20">
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-white text-sm shadow-sm dark:bg-blue-950/40">📎</span>
            <p className="text-xs font-medium">
              已添加 {attachments.length} 个附件
            </p>
          </div>
          <div className="space-y-2">
            {attachments.map((attachment) => (
              <div key={attachment.id} className="flex items-center gap-3 rounded-md border border-blue-100 bg-white/80 px-3 py-2 dark:border-blue-900/40 dark:bg-blue-950/20">
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{attachment.filename}</p>
                  <p className="text-[11px] text-text-secondary mt-0.5">
                    {attachment.fileType.toUpperCase()} · {formatSize(attachment.fileSize)} · {attachment.charCount} 字符
                  </p>
                </div>
                <button
                  onClick={() => removeAttachment(attachment.id)}
                  className="win-icon-button h-8 w-8 flex-shrink-0 text-sm"
                  title="移除附件"
                  aria-label={`移除附件 ${attachment.filename}`}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 上传中提示 */}
      {uploading && (
        <div className="mb-2 flex items-center gap-2 rounded-md border border-surface-divider dark:border-dark-divider bg-surface dark:bg-dark-sidebar px-3 py-2 text-xs text-text-secondary shadow-sm">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-white text-[11px] shadow-sm dark:bg-dark-card">⏳</span>
          <span>正在提取文件内容...</span>
        </div>
      )}

      <div className="rounded-lg border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-sidebar shadow-sm">
        <div className="flex items-end gap-3 px-3 py-3">
          {/* 隐藏的文件输入 */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp,image/*"
            className="hidden"
            onChange={handleFileChange}
          />
          {/* 附件按钮 */}
          <button
            onClick={triggerFileUpload}
            disabled={uploading}
            className="win-icon-button flex-shrink-0"
            title={uploading ? '提取中...' : '添加附件'}
            aria-label={uploading ? '正在提取附件' : '添加附件'}
          >
            {uploading ? '⏳' : '📎'}
          </button>

          {/* 输入框 */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              adjustHeight();
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              disabled
                ? '请先配置 API Key...'
                : attachments.length > 0
                  ? '输入提示词，或直接发送让 AI 分析这些附件内容...'
                  : '输入消息，Enter 发送，Shift+Enter 换行'
            }
            disabled={disabled}
            rows={1}
            className={clsx(
              'flex-1 min-h-[40px] max-h-[200px] resize-none border-0 bg-transparent px-0 py-2 text-sm leading-6',
              'focus:outline-none focus:ring-0 placeholder:text-text-secondary scrollbar-thin',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
          />

          {/* 发送/停止按钮 */}
          {isStreaming ? (
            <button
              onClick={onStop}
              className="inline-flex h-9 min-w-[72px] flex-shrink-0 items-center justify-center rounded-md bg-red-500 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-red-600"
              title="停止生成"
            >
              停止
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              className="win-button-primary h-9 min-w-[72px] flex-shrink-0 px-4 text-sm"
              title="发送"
            >
              发送
            </button>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-surface-divider dark:border-dark-divider px-3 py-2.5 flex-wrap">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <span className="text-xs text-text-secondary whitespace-nowrap">当前模型</span>
            <select
              value={activeLLMConfig?.id ?? ''}
              onChange={(e) => setActiveLLMConfig(e.target.value)}
              className="win-select min-w-[220px] max-w-full !py-1.5 text-xs"
            >
              {llmConfigs.map((config) => (
                <option key={config.id} value={config.id}>
                  {config.name} · {config.model}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={toggleSettings}
            className="win-button-subtle px-2 py-1 text-xs"
          >
            管理模型配置
          </button>
        </div>
      </div>

      {/* 底部提示 */}
      <p className="mt-2 pl-1 text-[11px] text-text-secondary">
        Version beta 0.2.0
      </p>
    </div>
  );
}
