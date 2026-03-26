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
import { useAppStore } from '@/stores/appStore';
import type { SystemPromptMap, SystemPromptPreset } from '@/types';

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
  const { roles } = useAppStore();
  const [prompts, setPrompts] = useState<SystemPromptMap>({});
  const [presets, setPresets] = useState<SystemPromptPreset[]>([]);
  const [presetNames, setPresetNames] = useState<Record<string, string>>({});
  const [collapsedModes, setCollapsedModes] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [busyModes, setBusyModes] = useState<Record<string, string>>({});
  const [presetBusyId, setPresetBusyId] = useState<string | null>(null);
  const [modeNotice, setModeNotice] = useState<Record<string, { ok: boolean; text: string } | undefined>>({});
  const [presetNotice, setPresetNotice] = useState<Record<string, { ok: boolean; text: string } | undefined>>({});
  const [error, setError] = useState('');

  // 当角色列表就绪时，初始化折叠状态和预设名称（仅做第一次初始化）
  useEffect(() => {
    if (roles.length === 0) return;
    setCollapsedModes((prev) => {
      const next = { ...prev };
      roles.forEach((r, i) => { if (!(r.id in next)) next[r.id] = i !== 0; });
      return next;
    });
    setPresetNames((prev) => {
      const next = { ...prev };
      roles.forEach((r) => { if (!(r.id in next)) next[r.id] = ''; });
      return next;
    });
  }, [roles]);

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
    () => Object.fromEntries(
      roles.map((role) => [role.id, presets.filter((preset) => preset.mode === role.id)])
    ) as Record<string, SystemPromptPreset[]>,
    [roles, presets],
  );

  const promptCount = useMemo(
    () => Object.values(prompts).reduce((total, text) => total + (text?.trim().length ?? 0), 0),
    [prompts],
  );

  const updatePrompt = (roleId: string, value: string) => {
    setPrompts((current) => ({ ...current, [roleId]: value }));
    setModeNotice((current) => ({ ...current, [roleId]: undefined }));
  };

  const togglePresetPanel = (roleId: string) => {
    setCollapsedModes((current) => ({ ...current, [roleId]: !current[roleId] }));
  };

  const saveModePrompt = async (roleId: string) => {
    setBusyModes((current) => ({ ...current, [roleId]: 'save' }));
    setModeNotice((current) => ({ ...current, [roleId]: undefined }));
    try {
      const result = await updateSystemPrompt(roleId, prompts[roleId] ?? '');
      setPrompts((current) => ({ ...current, [roleId]: result.prompt }));
      setModeNotice((current) => ({ ...current, [roleId]: { ok: true, text: '已保存' } }));
    } catch (err) {
      setModeNotice((current) => ({ ...current, [roleId]: { ok: false, text: (err as Error).message || '保存失败' } }));
    } finally {
      setBusyModes((current) => ({ ...current, [roleId]: '' }));
    }
  };

  const restoreDefault = async (roleId: string) => {
    setBusyModes((current) => ({ ...current, [roleId]: 'reset' }));
    setModeNotice((current) => ({ ...current, [roleId]: undefined }));
    try {
      const result = await resetSystemPrompt(roleId);
      setPrompts((current) => ({ ...current, [roleId]: result.prompt }));
      setModeNotice((current) => ({ ...current, [roleId]: { ok: true, text: '已恢复默认' } }));
    } catch (err) {
      setModeNotice((current) => ({ ...current, [roleId]: { ok: false, text: (err as Error).message || '恢复失败' } }));
    } finally {
      setBusyModes((current) => ({ ...current, [roleId]: '' }));
    }
  };

  const savePreset = async (roleId: string) => {
    setPresetNotice((current) => ({ ...current, [roleId]: undefined }));
    setBusyModes((current) => ({ ...current, [roleId]: 'preset' }));
    try {
      const result = await createSystemPromptPreset(presetNames[roleId] ?? '', roleId, prompts[roleId] ?? '');
      setPresetNames((current) => ({ ...current, [roleId]: '' }));
      setPresets((current) => [result.preset, ...current]);
      setPresetNotice((current) => ({ ...current, [roleId]: { ok: true, text: result.message } }));
    } catch (err) {
      setPresetNotice((current) => ({ ...current, [roleId]: { ok: false, text: (err as Error).message || '保存预设失败' } }));
    } finally {
      setBusyModes((current) => ({ ...current, [roleId]: '' }));
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

  return (
    <div className={clsx('grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_340px]', loading && 'opacity-50 pointer-events-none')}>
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
            {roles.map((role) => (
              <div key={role.id} className="rounded-lg border border-surface-divider bg-white px-4 py-4 shadow-sm dark:border-dark-divider dark:bg-dark-card">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h5 className="text-sm font-medium">{role.icon} {role.name}</h5>
                    {role.description && <p className="mt-1 text-xs text-text-secondary">{role.description}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => void saveModePrompt(role.id)}
                      disabled={Boolean(busyModes[role.id])}
                      className="win-button-primary h-8 px-3 text-xs"
                    >
                      {busyModes[role.id] === 'save' ? '保存中...' : '保存'}
                    </button>
                    <button
                      onClick={() => void restoreDefault(role.id)}
                      disabled={Boolean(busyModes[role.id])}
                      className="win-button h-8 px-3 text-xs"
                    >
                      {busyModes[role.id] === 'reset' ? '恢复中...' : '恢复默认'}
                    </button>
                  </div>
                </div>

                <textarea
                  value={prompts[role.id] ?? ''}
                  onChange={(event) => updatePrompt(role.id, event.target.value)}
                  rows={7}
                  className="win-input mt-3 resize-y text-sm leading-6"
                  placeholder={`填写 ${role.name} 的系统提示词`}
                />

                {modeNotice[role.id] && (
                  <p className={clsx('mt-2 text-xs', modeNotice[role.id]?.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                    {modeNotice[role.id]?.text}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="space-y-4">
        {roles.map((role) => (
          <div key={role.id} className="win-panel space-y-4 p-4">
            <button
              type="button"
              onClick={() => togglePresetPanel(role.id)}
              className="flex w-full items-center justify-between gap-3 text-left"
            >
              <div>
                <h4 className="text-sm font-medium">{role.icon} {role.name} 预设</h4>
              </div>
              <div className="flex items-center gap-2">
                <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
                  {(groupedPresets[role.id] ?? []).length}
                </span>
                <span className="text-xs text-text-secondary">
                  {collapsedModes[role.id] ? '展开' : '收起'}
                </span>
              </div>
            </button>

            {!collapsedModes[role.id] && (
              <>
                {presetNotice[role.id] && (
                  <div className={clsx(
                    'rounded-lg px-3 py-3 text-xs',
                    presetNotice[role.id]?.ok
                      ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-900/20 dark:text-emerald-300'
                      : 'border border-red-200 bg-red-50 text-red-600 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-300'
                  )}>
                    {presetNotice[role.id]?.text}
                  </div>
                )}

                <div className="space-y-2">
                  <input
                    type="text"
                    value={presetNames[role.id] ?? ''}
                    onChange={(event) => setPresetNames((current) => ({ ...current, [role.id]: event.target.value }))}
                    placeholder={`给 ${role.name} 这一项起个名字`}
                    className="win-input text-sm"
                  />
                  <button
                    onClick={() => void savePreset(role.id)}
                    disabled={Boolean(busyModes[role.id])}
                    className="win-button-primary h-8 w-full text-xs"
                  >
                    {busyModes[role.id] === 'preset' ? '保存中...' : '保存当前为预设'}
                  </button>
                </div>

                <div className="space-y-2 border-t border-surface-divider pt-4 dark:border-dark-divider">
                  {(groupedPresets[role.id] ?? []).length === 0 ? (
                    <p className="rounded-lg border border-dashed border-surface-divider px-3 py-4 text-xs text-text-secondary dark:border-dark-divider">
                      还没有保存过预设。
                    </p>
                  ) : (
                    (groupedPresets[role.id] ?? []).map((preset) => (
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
