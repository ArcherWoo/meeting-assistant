/**
 * 右侧上下文面板
 * 显示：Skill 列表（含增删改）、知识库统计、Know-how 规则库概览
 */
import { useState, useEffect, useCallback, useRef, type ChangeEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import {
  listSkills, getKnowledgeStats, getKnowhowStats,
  getSkillContent, saveSkill, updateSkill, deleteSkill,
  uploadFile, listKnowledgeImports, deleteKnowledgeImport,
} from '@/services/api';
import { MODE_CONFIG } from '@/types';
import type { SkillMeta, KnowledgeStats } from '@/types';

/** 已导入文件记录 */
interface ImportRecord {
  id: string;
  file_name: string;
  file_size: number;
  slide_count: number;
  import_status: string;
  imported_at: string;
}

export default function ContextPanel() {
  const { toggleContextPanel, currentMode } = useAppStore();
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [kbStats, setKbStats] = useState<KnowledgeStats | null>(null);
  const [khStats, setKhStats] = useState<{ total_rules: number; active_rules: number } | null>(null);

  // 知识库导入状态
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [importing, setImporting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const kbFileInputRef = useRef<HTMLInputElement>(null);

  // Skill 编辑器状态
  // isNew=true 表示新建 Skill；originalIsBuiltin 记录原始的 is_builtin（便于提示）
  const [editingSkill, setEditingSkill] = useState<{
    id: string; name: string; content: string; is_builtin: boolean; isNew: boolean; originalIsBuiltin: boolean;
  } | null>(null);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [deletingSkillId, setDeletingSkillId] = useState<string | null>(null);

  /** 刷新所有数据 */
  const refresh = useCallback(async () => {
    try {
      const [s, kb, kh, imp] = await Promise.allSettled([
        listSkills(), getKnowledgeStats(), getKnowhowStats(), listKnowledgeImports(),
      ]);
      if (s.status === 'fulfilled') setSkills(s.value);
      if (kb.status === 'fulfilled') setKbStats(kb.value);
      if (kh.status === 'fulfilled') setKhStats(kh.value);
      if (imp.status === 'fulfilled') setImports(imp.value.imports || []);
    } catch { /* 静默处理 */ }
  }, []);

  /** 知识库导入文件 */
  const handleKbImport = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setImporting(true);
    try {
      await uploadFile(file);
      await refresh();
    } catch (err: any) {
      alert(`导入失败：${err.message || '未知错误'}`);
    } finally {
      setImporting(false);
    }
  };

  /** 删除知识库记录 */
  const handleDeleteImport = async (importId: string, fileName: string) => {
    if (!confirm(`确定要删除「${fileName}」及其所有向量数据吗？`)) return;
    setDeletingId(importId);
    try {
      await deleteKnowledgeImport(importId);
      await refresh();
    } catch (err: any) {
      alert(`删除失败：${err.message || '未知错误'}`);
    } finally {
      setDeletingId(null);
    }
  };

  // 初始加载 + 模式切换时刷新
  useEffect(() => { refresh(); }, [currentMode, refresh]);

  // 定时轮询刷新（每 10 秒）
  useEffect(() => {
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  /** 新建 Skill 模板 */
  const NEW_SKILL_TEMPLATE = `# Skill: 新技能名称

## 描述
在此描述该 Skill 的功能和适用场景。

## 触发条件
- 关键词: "关键词1", "关键词2"
- 输入类型: .pptx 文件

## 执行步骤
1. 第一步描述
2. 第二步描述
3. 第三步描述

## 输出格式
在此描述输出格式。
`;

  /** 打开新建 Skill 编辑器 */
  const handleNewSkill = () => {
    setEditingSkill({ id: '', name: '新 Skill', content: NEW_SKILL_TEMPLATE, is_builtin: false, isNew: true, originalIsBuiltin: false });
    setEditContent(NEW_SKILL_TEMPLATE);
    setSaveMsg('');
  };

  /** 点击 Skill 卡片 → 加载内容并打开编辑器 */
  const handleSkillClick = async (skill: SkillMeta) => {
    try {
      const data = await getSkillContent(skill.id);
      setEditingSkill({ id: skill.id, name: skill.name, content: data.content, is_builtin: data.is_builtin, isNew: false, originalIsBuiltin: data.is_builtin });
      setEditContent(data.content);
      setSaveMsg('');
    } catch (err: any) {
      alert(`无法加载 Skill 内容: ${err.message}`);
    }
  };

  /** 保存编辑后的 Skill（新建或更新） */
  const handleSaveSkill = async () => {
    if (!editingSkill) return;
    setSaving(true);
    setSaveMsg('');
    try {
      let result;
      if (editingSkill.isNew) {
        result = await saveSkill(editContent);
      } else {
        result = await updateSkill(editingSkill.id, editContent);
      }
      setSaveMsg(`✅ ${result.message}`);
      await refresh();
      // 新建成功后更新编辑器状态为已保存的 skill
      if (editingSkill.isNew) {
        setEditingSkill((prev) => prev ? { ...prev, id: result.id, name: result.name, isNew: false } : null);
      }
    } catch (err: any) {
      setSaveMsg(`❌ ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  /** 删除 Skill（内置 Skill 写入墓碑标记实现逻辑删除，用户 Skill 直接删除文件） */
  const handleDeleteSkill = async (skill: SkillMeta, e: React.MouseEvent) => {
    e.stopPropagation();
    const builtinNote = skill.is_builtin
      ? '\n（这是内置 Skill，删除后将不再出现，重启后依然生效）'
      : '';
    if (!confirm(`确定要删除 Skill「${skill.name}」吗？${builtinNote}`)) return;
    setDeletingSkillId(skill.id);
    try {
      await deleteSkill(skill.id);
      await refresh();
    } catch (err: any) {
      alert(`删除失败：${err.message}`);
    } finally {
      setDeletingSkillId(null);
    }
  };

  // ===== 编辑器视图 =====
  if (editingSkill) {
    return (
      <aside className="w-[300px] flex-shrink-0 border-l border-surface-divider dark:border-dark-divider bg-[#F7F8FA] dark:bg-dark flex flex-col">
        <div className="win-toolbar flex h-12 items-center justify-between px-3">
          <button onClick={() => setEditingSkill(null)} className="win-button-subtle h-8 px-2 text-xs">← 返回</button>
          <h3 className="text-sm font-medium truncate flex-1 mx-2">
            {editingSkill.isNew ? '✨ 新建 Skill' : editingSkill.name}
          </h3>
          <button onClick={toggleContextPanel} className="win-icon-button h-8 w-8">✕</button>
        </div>
        <div className="flex-1 flex flex-col gap-3 overflow-hidden p-3">
          {editingSkill.originalIsBuiltin && !editingSkill.isNew && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
              📋 内置 Skill — 保存后将在用户目录创建自定义版本，不修改内置文件
            </p>
          )}
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 w-full resize-none rounded-lg border border-surface-divider dark:border-dark-divider bg-white p-3 font-mono text-xs leading-6 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20 dark:bg-dark-card"
            spellCheck={false}
            placeholder="按 Skill Markdown 格式编写..."
          />
          {saveMsg && <p className="text-xs text-text-secondary">{saveMsg}</p>}
          <button
            onClick={handleSaveSkill}
            disabled={saving}
            className="win-button-primary h-9 w-full text-sm"
          >
            {saving
              ? '保存中...'
              : editingSkill.isNew
                ? '💾 创建 Skill'
                : editingSkill.originalIsBuiltin
                  ? '💾 保存为自定义版本'
                  : '💾 保存修改'}
          </button>
        </div>
      </aside>
    );
  }

  // ===== 正常列表视图 =====
  return (
    <aside className="w-[300px] flex-shrink-0 border-l border-surface-divider dark:border-dark-divider bg-[#F7F8FA] dark:bg-dark flex flex-col">
      <div className="win-toolbar flex h-12 items-center justify-between px-3">
        <h3 className="text-sm font-medium">上下文</h3>
        <button onClick={toggleContextPanel} className="win-icon-button h-8 w-8">✕</button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-3.5">
        <div className="space-y-4">
          {/* 当前模式 */}
          <section>
            <h4 className="win-section-title mb-2">当前模式</h4>
            <div className="win-panel-muted px-3 py-3 text-sm font-medium text-primary">
              {MODE_CONFIG[currentMode].icon} {MODE_CONFIG[currentMode].label} 模式
            </div>
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* Skill 列表 */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h4 className="win-section-title">
                可用 Skill ({skills.length})
              </h4>
              <div className="flex items-center gap-1.5">
                <button onClick={refresh} className="win-icon-button h-7 w-7 text-[11px]" title="刷新">↻</button>
                <button
                  onClick={handleNewSkill}
                  className="win-button-primary h-7 px-2.5 text-[11px]"
                >
                  + 新建
                </button>
              </div>
            </div>
            {skills.length === 0 ? (
              <p className="text-xs text-text-secondary text-center py-3">暂无 Skill</p>
            ) : (
              <div className="space-y-1.5">
                {skills.map((skill) => (
                  <div
                    key={skill.id}
                    className="group rounded-lg border border-surface-divider dark:border-dark-divider bg-white px-3 py-2.5 text-xs shadow-sm transition-colors hover:border-primary/30 dark:bg-dark-card"
                  >
                    <div className="flex items-start justify-between gap-1">
                      <p className="font-medium flex-1 min-w-0 truncate">{skill.name}</p>
                      {/* 操作按钮 - hover 时显示 */}
                      <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => handleSkillClick(skill)}
                          className="win-icon-button h-7 w-7 text-[11px]"
                          title="编辑"
                        >
                          ✏️
                        </button>
                        <button
                          onClick={(e) => handleDeleteSkill(skill, e)}
                          disabled={deletingSkillId === skill.id}
                          className="win-icon-button h-7 w-7 text-[11px] disabled:opacity-50"
                          title={skill.is_builtin ? '删除（逻辑删除，重启后生效）' : '删除'}
                        >
                          {deletingSkillId === skill.id ? '⏳' : '🗑'}
                        </button>
                      </div>
                    </div>
                    <p className="mt-1 line-clamp-2 cursor-pointer text-text-secondary" onClick={() => handleSkillClick(skill)}>{skill.description}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {skill.keywords.slice(0, 3).map((kw) => (
                        <span key={kw} className="win-chip text-[10px]">{kw}</span>
                      ))}
                      {skill.is_builtin && (
                        <span className="win-badge border-blue-200 bg-blue-50 text-[10px] text-blue-600 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400">内置</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* 知识库管理 */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h4 className="win-section-title">知识库</h4>
              <div className="flex items-center gap-1">
                <input
                  ref={kbFileInputRef}
                  type="file"
                  accept=".ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp"
                  className="hidden"
                  onChange={handleKbImport}
                />
                <button
                  onClick={() => kbFileInputRef.current?.click()}
                  disabled={importing}
                  className="win-button-primary h-7 px-2.5 text-[11px]"
                >
                  {importing ? '导入中...' : '导入文件'}
                </button>
              </div>
            </div>

            {/* 统计卡片 */}
            {kbStats && (
              <div className="grid grid-cols-2 gap-2 mb-2">
                <StatCard label="文件导入" value={kbStats.total_ppt_imports} />
                <StatCard label="向量块" value={kbStats.total_vector_chunks} />
              </div>
            )}

            {/* 已导入文件列表 */}
            {imports.length > 0 ? (
              <div className="space-y-1 mt-2">
                <p className="text-[10px] text-text-secondary mb-1">已导入文件 ({imports.length})</p>
                {imports.map((imp) => (
                  <div key={imp.id} className="group flex items-center gap-2 rounded-md border border-surface-divider dark:border-dark-divider bg-white px-2.5 py-2 text-xs shadow-sm dark:bg-dark-card">
                    <span className="text-[10px]">📄</span>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-[11px] font-medium">{imp.file_name}</p>
                    </div>
                    <button
                      onClick={() => handleDeleteImport(imp.id, imp.file_name)}
                      disabled={deletingId === imp.id}
                      className="win-icon-button h-7 w-7 flex-shrink-0 text-[11px] opacity-0 transition-all group-hover:opacity-100 disabled:opacity-50"
                      title="删除"
                    >
                      {deletingId === imp.id ? '⏳' : '🗑'}
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-secondary text-center py-2">暂无导入文件</p>
            )}
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* Know-how 规则库概览 */}
          <section>
            <h4 className="win-section-title mb-2">Know-how 规则库</h4>
            {khStats ? (
              <div className="win-panel-muted px-3 py-3 text-xs text-text-secondary">
                共 {khStats.total_rules} 条规则，{khStats.active_rules} 条启用
              </div>
            ) : (
              <p className="text-xs text-text-secondary text-center py-3">加载中...</p>
            )}
          </section>
        </div>
      </div>
    </aside>
  );
}

/** 统计数字卡片 */
function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="win-panel-muted px-3 py-3 text-center">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-[10px] text-text-secondary">{label}</p>
    </div>
  );
}
