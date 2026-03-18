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
      <aside className="w-[280px] flex-shrink-0 border-l border-surface-divider dark:border-dark-divider bg-surface dark:bg-dark flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-divider dark:border-dark-divider">
          <button onClick={() => setEditingSkill(null)}
            className="text-xs text-primary hover:underline">← 返回</button>
          <h3 className="text-sm font-medium truncate flex-1 mx-2">
            {editingSkill.isNew ? '✨ 新建 Skill' : editingSkill.name}
          </h3>
          <button onClick={toggleContextPanel}
            className="text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors">✕</button>
        </div>
        <div className="flex-1 flex flex-col p-3 gap-2 overflow-hidden">
          {editingSkill.originalIsBuiltin && !editingSkill.isNew && (
            <p className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded px-2 py-1">
              📋 内置 Skill — 保存后将在用户目录创建自定义版本，不修改内置文件
            </p>
          )}
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 w-full text-xs font-mono p-2 rounded-lg border border-surface-divider dark:border-dark-divider bg-surface-card dark:bg-dark-card resize-none focus:outline-none focus:ring-1 focus:ring-primary"
            spellCheck={false}
            placeholder="按 Skill Markdown 格式编写..."
          />
          {saveMsg && <p className="text-xs">{saveMsg}</p>}
          <button
            onClick={handleSaveSkill}
            disabled={saving}
            className="w-full py-1.5 text-xs font-medium rounded-lg bg-primary text-white hover:bg-primary/90 disabled:opacity-50 transition-colors"
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
    <aside className="w-[280px] flex-shrink-0 border-l border-surface-divider dark:border-dark-divider bg-surface dark:bg-dark flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-divider dark:border-dark-divider">
        <h3 className="text-sm font-medium">上下文</h3>
        <button onClick={toggleContextPanel}
          className="text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors">✕</button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
        <div className="space-y-4">
          {/* 当前模式 */}
          <section>
            <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wider mb-2">当前模式</h4>
            <div className="px-3 py-2 rounded-lg bg-primary/10 text-sm font-medium text-primary">
              {MODE_CONFIG[currentMode].icon} {MODE_CONFIG[currentMode].label} 模式
            </div>
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* Skill 列表 */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
                可用 Skill ({skills.length})
              </h4>
              <div className="flex items-center gap-1.5">
                <button onClick={refresh} className="text-[10px] text-primary hover:underline">🔄</button>
                <button
                  onClick={handleNewSkill}
                  className="text-[10px] px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/90 transition-colors"
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
                    className="px-3 py-2 rounded-lg bg-surface-card dark:bg-dark-card text-xs hover:ring-1 hover:ring-primary/50 transition-all group"
                  >
                    <div className="flex items-start justify-between gap-1">
                      <p className="font-medium flex-1 min-w-0 truncate">{skill.name}</p>
                      {/* 操作按钮 - hover 时显示 */}
                      <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => handleSkillClick(skill)}
                          className="text-[11px] text-text-secondary hover:text-primary transition-colors"
                          title="编辑"
                        >
                          ✏️
                        </button>
                        <button
                          onClick={(e) => handleDeleteSkill(skill, e)}
                          disabled={deletingSkillId === skill.id}
                          className="text-[11px] text-text-secondary hover:text-red-500 transition-colors disabled:opacity-50"
                          title={skill.is_builtin ? '删除（逻辑删除，重启后生效）' : '删除'}
                        >
                          {deletingSkillId === skill.id ? '⏳' : '🗑'}
                        </button>
                      </div>
                    </div>
                    <p className="text-text-secondary mt-0.5 line-clamp-2 cursor-pointer" onClick={() => handleSkillClick(skill)}>{skill.description}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {skill.keywords.slice(0, 3).map((kw) => (
                        <span key={kw} className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px]">{kw}</span>
                      ))}
                      {skill.is_builtin && (
                        <span className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 text-[10px]">内置</span>
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
              <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wider">知识库</h4>
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
                  className="text-[10px] px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  {importing ? '导入中...' : '📥 导入文件'}
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
                  <div key={imp.id} className="flex items-center gap-1.5 px-2 py-1.5 rounded-md bg-surface-card dark:bg-dark-card text-xs group">
                    <span className="text-[10px]">📄</span>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-[11px]">{imp.file_name}</p>
                    </div>
                    <button
                      onClick={() => handleDeleteImport(imp.id, imp.file_name)}
                      disabled={deletingId === imp.id}
                      className="flex-shrink-0 text-[10px] text-text-secondary hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all disabled:opacity-50"
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
            <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wider mb-2">Know-how 规则库</h4>
            {khStats ? (
              <p className="text-xs text-text-secondary">
                共 {khStats.total_rules} 条规则，{khStats.active_rules} 条启用
              </p>
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
    <div className="px-3 py-2 rounded-lg bg-surface-card dark:bg-dark-card text-center">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-[10px] text-text-secondary">{label}</p>
    </div>
  );
}
