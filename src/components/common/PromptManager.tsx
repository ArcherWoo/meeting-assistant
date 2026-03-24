import { useCallback, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';

import {
  createSystemPromptPreset,
  deleteSystemPromptPreset,
  getSystemPrompts,
  listSystemPromptPresets,
  resetSystemPrompt,
  updateSystemPrompt,
} from '@/services/api';
import type { AppMode, SystemPromptMap, SystemPromptPreset } from '@/types';

const MODES: Array<{ key: AppMode; label: string; description: string }> = [
  { key: 'copilot', label: 'Copilot', description: '日常问答、分析、总结时使用。' },
  { key: 'builder', label: 'Skill Builder', description: '设计 Skill、流程和提示词时使用。' },
  { key: 'agent', label: 'Agent', description: '需要分步执行、透明反馈时使用。' },
];

const emptyPrompts = (): SystemPromptMap => ({
  copilot: '',
  builder: '',
  agent: '',
});

function formatTime(value: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function PromptManager() {
  const [prompts, setPrompts] = useState<SystemPromptMap>(emptyPrompts());
  const [presets, setPresets] = useState<SystemPromptPreset[]>([]);
  const [presetNames, setPresetNames] = useState<Record<AppMode, string>>({
    copilot: '',
    builder: '',
    agent: '',
  });
  const [collapsedModes, setCollapsedModes] = useState<Record<AppMode, boolean>>({
    copilot: false,
    builder: true,
    agent: true,
  });
  const [loading, setLoading] = useState(false);
  const [busyModes, setBusyModes] = useState<Partial<Record<AppMode, string>>>({});
  const [presetBusyId, setPresetBusyId] = useState<string | null>(null);
  const [modeNotice, setModeNotice] = useState<Partial<Record<AppMode, { ok: boolean; text: string }>>>({});
  const [presetNotice, setPresetNotice] = useState<Partial<Record<AppMode, { ok: boolean; text: string }>>>({});
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [promptResult, presetResult] = await Promise.all([
        getSystemPrompts(),
        listSystemPromptPresets(),
      ]);
      setPrompts(promptResult.prompts);
      setPresets(presetResult);
    } catch (err) {
      setError((err as Error).message || '加载 System Prompts 失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const groupedPresets = useMemo(
    () =>
      Object.fromEntries(
        MODES.map((mode) => [mode.key, presets.filter((preset) => preset.mode === mode.key)]),
      ) as Record<AppMode, SystemPromptPreset[]>,
    [presets],
  );

  const promptCount = useMemo(
    () => MODES.reduce((total, mode) => total + prompts[mode.key].trim().length, 0),
    [prompts],
  );

  const updatePrompt = (mode: AppMode, value: string) => {
    setPrompts((current) => ({ ...current, [mode]: value }));
    setModeNotice((current) => ({ ...current, [mode]: undefined }));
  };

  const togglePresetPanel = (mode: AppMode) => {
    setCollapsedModes((current) => ({ ...current, [mode]: !current[mode] }));
  };

  const saveModePrompt = async (mode: AppMode) => {
    setBusyModes((current) => ({ ...current, [mode]: 'save' }));
    setModeNotice((current) => ({ ...current, [mode]: undefined }));
    try {
      const result = await updateSystemPrompt(mode, prompts[mode]);
      setPrompts((current) => ({ ...current, [mode]: result.prompt }));
      setModeNotice((current) => ({ ...current, [mode]: { ok: true, text: '已保存' } }));
    } catch (err) {
      setModeNotice((current) => ({ ...current, [mode]: { ok: false, text: (err as Error).message || '保存失败' } }));
    } finally {
      setBusyModes((current) => ({ ...current, [mode]: '' }));
    }
  };

  const restoreDefault = async (mode: AppMode) => {
    setBusyModes((current) => ({ ...current, [mode]: 'reset' }));
    setModeNotice((current) => ({ ...current, [mode]: undefined }));
    try {
      const result = await resetSystemPrompt(mode);
      setPrompts((current) => ({ ...current, [mode]: result.prompt }));
      setModeNotice((current) => ({ ...current, [mode]: { ok: true, text: '已恢复默认' } }));
    } catch (err) {
      setModeNotice((current) => ({ ...current, [mode]: { ok: false, text: (err as Error).message || '恢复失败' } }));
    } finally {
      setBusyModes((current) => ({ ...current, [mode]: '' }));
    }
  };

  const savePreset = async (mode: AppMode) => {
    setPresetNotice((current) => ({ ...current, [mode]: undefined }));
    setBusyModes((current) => ({ ...current, [mode]: 'preset' }));
    try {
      const result = await createSystemPromptPreset(presetNames[mode], mode, prompts[mode]);
      setPresetNames((current) => ({ ...current, [mode]: '' }));
      setPresets((current) => [result.preset, ...current]);
      setPresetNotice((current) => ({ ...current, [mode]: { ok: true, text: result.message } }));
    } catch (err) {
      setPresetNotice((current) => ({ ...current, [mode]: { ok: false, text: (err as Error).message || '保存预设失败' } }));
    } finally {
      setBusyModes((current) => ({ ...current, [mode]: '' }));
    }
  };

  const importPreset = async (preset: SystemPromptPreset) => {
    const mode = preset.mode;
    setPresetBusyId(preset.id);
    setPresetNotice((current) => ({ ...current, [mode]: undefined }));
    setModeNotice((current) => ({ ...current, [mode]: undefined }));
    try {
      const result = await updateSystemPrompt(mode, preset.prompt);
      setPrompts((current) => ({ ...current, [mode]: result.prompt }));
      setModeNotice((current) => ({ ...current, [mode]: { ok: true, text: `已导入预设「${preset.name}」` } }));
    } catch (err) {
      setPresetNotice((current) => ({ ...current, [mode]: { ok: false, text: (err as Error).message || '导入预设失败' } }));
    } finally {
      setPresetBusyId(null);
    }
  };

  const removePreset = async (preset: SystemPromptPreset) => {
    if (!window.confirm(`确定删除预设「${preset.name}」吗？`)) return;
    setPresetBusyId(preset.id);
    setPresetNotice((current) => ({ ...current, [preset.mode]: undefined }));
    try {
      const result = await deleteSystemPromptPreset(preset.id);
      setPresets((current) => current.filter((item) => item.id !== preset.id));
      setPresetNotice((current) => ({ ...current, [preset.mode]: { ok: true, text: result.message } }));
    } catch (err) {
      setPresetNotice((current) => ({ ...current, [preset.mode]: { ok: false, text: (err as Error).message || '删除预设失败' } }));
    } finally {
      setPresetBusyId(null);
    }
  };

  if (loading) {
    return <div className="win-panel px-4 py-6 text-sm text-text-secondary">正在加载 System Prompts...</div>;
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_340px]">
      <section className="space-y-4">
        <div className="win-panel space-y-4 p-4">
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-sm font-medium">系统提示词</h4>
            <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
              共 {promptCount} 字
            </span>
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-xs text-red-600 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-300">
              {error}
            </div>
          )}

          <div className="space-y-4">
            {MODES.map((mode) => (
              <div key={mode.key} className="rounded-lg border border-surface-divider bg-white px-4 py-4 shadow-sm dark:border-dark-divider dark:bg-dark-card">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h5 className="text-sm font-medium">{mode.label}</h5>
                    <p className="mt-1 text-xs text-text-secondary">{mode.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => void saveModePrompt(mode.key)}
                      disabled={Boolean(busyModes[mode.key])}
                      className="win-button-primary h-8 px-3 text-xs"
                    >
                      {busyModes[mode.key] === 'save' ? '保存中...' : '保存'}
                    </button>
                    <button
                      onClick={() => void restoreDefault(mode.key)}
                      disabled={Boolean(busyModes[mode.key])}
                      className="win-button h-8 px-3 text-xs"
                    >
                      {busyModes[mode.key] === 'reset' ? '恢复中...' : '恢复默认'}
                    </button>
                  </div>
                </div>

                <textarea
                  value={prompts[mode.key]}
                  onChange={(event) => updatePrompt(mode.key, event.target.value)}
                  rows={7}
                  className="win-input mt-3 resize-y text-sm leading-6"
                  placeholder={`填写 ${mode.label} 的系统提示词`}
                />

                {modeNotice[mode.key] && (
                  <p className={clsx('mt-2 text-xs', modeNotice[mode.key]?.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                    {modeNotice[mode.key]?.text}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="space-y-4">
        {MODES.map((mode) => (
          <div key={mode.key} className="win-panel space-y-4 p-4">
            <button
              type="button"
              onClick={() => togglePresetPanel(mode.key)}
              className="flex w-full items-center justify-between gap-3 text-left"
            >
              <div>
                <h4 className="text-sm font-medium">{mode.label} 预设</h4>
              </div>
              <div className="flex items-center gap-2">
                <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
                  {groupedPresets[mode.key].length}
                </span>
                <span className="text-xs text-text-secondary">
                  {collapsedModes[mode.key] ? '展开' : '收起'}
                </span>
              </div>
            </button>

            {!collapsedModes[mode.key] && (
              <>
                {presetNotice[mode.key] && (
                  <div className={clsx(
                    'rounded-lg px-3 py-3 text-xs',
                    presetNotice[mode.key]?.ok
                      ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-900/20 dark:text-emerald-300'
                      : 'border border-red-200 bg-red-50 text-red-600 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-300'
                  )}>
                    {presetNotice[mode.key]?.text}
                  </div>
                )}

                <div className="space-y-2">
                  <input
                    type="text"
                    value={presetNames[mode.key]}
                    onChange={(event) => setPresetNames((current) => ({ ...current, [mode.key]: event.target.value }))}
                    placeholder={`给 ${mode.label} 这一项起个名字`}
                    className="win-input text-sm"
                  />
                  <button
                    onClick={() => void savePreset(mode.key)}
                    disabled={Boolean(busyModes[mode.key])}
                    className="win-button-primary h-8 w-full text-xs"
                  >
                    {busyModes[mode.key] === 'preset' ? '保存中...' : '保存当前为预设'}
                  </button>
                </div>

                <div className="space-y-2 border-t border-surface-divider pt-4 dark:border-dark-divider">
                  {groupedPresets[mode.key].length === 0 ? (
                    <p className="rounded-lg border border-dashed border-surface-divider px-3 py-4 text-xs text-text-secondary dark:border-dark-divider">
                      还没有保存过预设。
                    </p>
                  ) : (
                    groupedPresets[mode.key].map((preset) => (
                      <div key={preset.id} className="rounded-lg border border-surface-divider bg-white px-3 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-card">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium">{preset.name}</p>
                            <p className="mt-1 text-[11px] text-text-secondary">
                              保存于 {formatTime(preset.updated_at || preset.created_at) || '刚刚'}
                            </p>
                          </div>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => void importPreset(preset)}
                              disabled={presetBusyId === preset.id}
                              className="win-button h-8 px-2 text-[11px]"
                            >
                              {presetBusyId === preset.id ? '导入中...' : '导入'}
                            </button>
                            <button
                              onClick={() => void removePreset(preset)}
                              disabled={presetBusyId === preset.id}
                              className="win-button h-8 px-2 text-[11px]"
                            >
                              {presetBusyId === preset.id ? '处理中...' : '删除'}
                            </button>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
