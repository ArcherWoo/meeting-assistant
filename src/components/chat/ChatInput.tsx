/**
 * 聊天输入组件
 * 自动扩展的文本输入框 + 附件上传（提取文本作为上下文） + 发送/停止按钮
 */
import { useState, useRef, useCallback, type KeyboardEvent, type ChangeEvent } from 'react';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import { extractFileText } from '@/services/api';

/** 附件信息 */
interface Attachment {
  filename: string;
  fileType: string;
  fileSize: number;
  text: string;
  charCount: number;
}

interface Props {
  /** 发送消息（content + 可选附件文本上下文） */
  onSend: (content: string, attachmentContext?: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export default function ChatInput({ onSend, onStop, isStreaming, disabled }: Props) {
  const { llmConfigs, activeLLMConfigId, setActiveLLMConfig, toggleSettings } = useAppStore();
  const [input, setInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeLLMConfig = llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0];

  /** 触发文件选择 */
  const triggerFileUpload = () => fileInputRef.current?.click();

  /** 处理文件选择 → 提取文本作为附件 */
  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';

    setUploading(true);
    try {
      const result = await extractFileText(file);
      setAttachment({
        filename: result.filename,
        fileType: result.file_type,
        fileSize: file.size,
        text: result.text,
        charCount: result.char_count,
      });
    } catch (err: any) {
      // 提取失败时显示错误提示
      alert(`文件文本提取失败：${err.message || '未知错误'}`);
    } finally {
      setUploading(false);
    }
  };

  /** 移除附件 */
  const removeAttachment = () => setAttachment(null);

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
    if (!trimmed && !attachment) return;
    if (isStreaming) return;

    const userMessage = trimmed || '请分析这份文件的内容';
    const attachmentContext = attachment
      ? `\n\n---\n📎 附件「${attachment.filename}」内容（${attachment.charCount} 字符）：\n\n${attachment.text}`
      : undefined;

    onSend(userMessage, attachmentContext);
    setInput('');
    setAttachment(null);
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

  const canSend = (input.trim() || attachment) && !disabled;

  return (
    <div className="border-t border-surface-divider dark:border-dark-divider bg-surface-card dark:bg-dark-card px-4 py-3">
      {/* API Key 未配置提示 */}
      {disabled && (
        <div className="text-xs text-amber-600 dark:text-amber-400 mb-2 flex items-center gap-1">
          <span>⚠️</span>
          <span>请先在设置中配置 API Key</span>
        </div>
      )}

      {/* 附件预览 */}
      {attachment && (
        <div className="mb-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
          <span className="text-sm">📎</span>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium truncate">{attachment.filename}</p>
            <p className="text-[10px] text-text-secondary">
              {attachment.fileType.toUpperCase()} · {formatSize(attachment.fileSize)} · {attachment.charCount} 字符
            </p>
          </div>
          <button
            onClick={removeAttachment}
            className="flex-shrink-0 text-text-secondary hover:text-red-500 transition-colors text-sm"
            title="移除附件"
          >
            ✕
          </button>
        </div>
      )}

      {/* 上传中提示 */}
      {uploading && (
        <div className="mb-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800 text-xs text-text-secondary">
          <span>⏳</span>
          <span>正在提取文件内容...</span>
        </div>
      )}

      <div className="flex items-end gap-2">
        {/* 隐藏的文件输入 */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp,image/*"
          className="hidden"
          onChange={handleFileChange}
        />
        {/* 附件按钮 */}
        <button
          onClick={triggerFileUpload}
          disabled={uploading}
          className={clsx(
            'flex-shrink-0 p-2 text-text-secondary hover:text-primary transition-colors rounded-button hover:bg-gray-100 dark:hover:bg-gray-800',
            uploading && 'opacity-50 cursor-wait'
          )}
          title={uploading ? '提取中...' : '添加附件'}
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
              : attachment
                ? '输入提示词，或直接发送让 AI 分析附件内容...'
                : '输入消息，Enter 发送，Shift+Enter 换行'
          }
          disabled={disabled}
          rows={1}
          className={clsx(
            'flex-1 resize-none rounded-input border border-surface-divider dark:border-dark-divider',
            'bg-surface dark:bg-dark px-3 py-2 text-sm',
            'focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary',
            'placeholder:text-text-secondary transition-all',
            'scrollbar-thin',
            disabled && 'opacity-50 cursor-not-allowed'
          )}
        />

        {/* 发送/停止按钮 */}
        {isStreaming ? (
          <button
            onClick={onStop}
            className="flex-shrink-0 p-2 bg-red-500 text-white rounded-button hover:bg-red-600 transition-colors"
            title="停止生成"
          >
            ⏹
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!canSend}
            className={clsx(
              'flex-shrink-0 p-2 rounded-button transition-colors',
              canSend
                ? 'bg-primary text-white hover:bg-primary-600'
                : 'bg-gray-200 dark:bg-gray-700 text-text-secondary cursor-not-allowed'
            )}
            title="发送"
          >
            ↑
          </button>
        )}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs text-text-secondary whitespace-nowrap">当前模型</span>
          <select
            value={activeLLMConfig?.id ?? ''}
            onChange={(e) => setActiveLLMConfig(e.target.value)}
            className="min-w-[220px] max-w-full px-2.5 py-1 text-xs rounded-md border border-surface-divider dark:border-dark-divider bg-surface dark:bg-dark"
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
          className="text-xs text-primary hover:text-primary-600 transition-colors"
        >
          管理模型配置
        </button>
      </div>

      {/* 底部提示 */}
      <p className="text-xs text-text-secondary mt-1.5 text-center">
        Meeting Assistant 可能会犯错，请核实重要信息
      </p>
    </div>
  );
}

