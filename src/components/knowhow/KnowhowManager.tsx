/**
 * Know-how 规则库管理界面
 * 支持规则的 CRUD 操作、分类筛选、启用/禁用
 * 分类增删改操作内联在筛选行中，无独立 Tab
 */
import { useState, useEffect, useCallback, useMemo, useRef, type ChangeEvent } from 'react';
import clsx from 'clsx';
import {
  listKnowhowRules, createKnowhowRule, updateKnowhowRule,
  deleteKnowhowRule, getKnowhowStats,
  renameKnowhowCategory, deleteKnowhowCategory,
  exportKnowhowRules, importKnowhowRules,
} from '@/services/api';
import type { KnowhowExportData, KnowhowImportStrategy, KnowhowRule } from '@/types';

/** 规则分类选项 */
const PRESET_CATEGORIES = ['采购预审', '合规性', '价格合理性', '技术规格', '供应商资质', '流程规范', '其他'] as const;
type RuleStatusFilter = 'all' | 'active' | 'inactive';

function getImportRuleCount(payload: unknown): number {
  if (Array.isArray(payload)) return payload.length;
  if (payload && typeof payload === 'object' && Array.isArray((payload as { rules?: unknown[] }).rules)) {
    return (payload as { rules: unknown[] }).rules.length;
  }
  return 0;
}

function downloadKnowhowExport(data: KnowhowExportData) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const exportDate = data.exported_at?.slice(0, 10) || new Date().toISOString().slice(0, 10);

  anchor.href = url;
  anchor.download = `knowhow-rules-${exportDate}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

function buildImportNotice(result: {
  strategy: KnowhowImportStrategy;
  total_in_file: number;
  imported_count: number;
  skipped_count: number;
  deleted_count: number;
  total_after_import: number;
}): string {
  const action = result.strategy === 'replace' ? `已覆盖导入，先清空了 ${result.deleted_count} 条旧规则。` : '已追加导入。';
  const skipped = result.skipped_count > 0 ? `跳过重复 ${result.skipped_count} 条。` : '';
  return `${action} 本次读取 ${result.total_in_file} 条，成功导入 ${result.imported_count} 条。${skipped} 当前共有 ${result.total_after_import} 条规则。`;
}

interface Props {
  /** 是否作为独立面板展示（vs 嵌入 ContextPanel） */
  standalone?: boolean;
}

export default function KnowhowManager({ standalone = true }: Props) {
  const [rules, setRules] = useState<KnowhowRule[]>([]);
  // 后端返回 { total_rules, active_rules, categories: string[], total_hits }
  const [stats, setStats] = useState<{ total_rules: number; active_rules: number; categories: string[]; total_hits: number } | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<RuleStatusFilter>('all');
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<'import' | 'export' | ''>('');
  const [editingRule, setEditingRule] = useState<Partial<KnowhowRule> | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [pendingImport, setPendingImport] = useState<{ fileName: string; ruleCount: number; payload: unknown } | null>(null);
  const [importStrategy, setImportStrategy] = useState<KnowhowImportStrategy>('append');

  // 分类内联管理状态
  const [renamingCat, setRenamingCat] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [deletingCat, setDeletingCat] = useState<string | null>(null);
  const [deleteRules, setDeleteRulesFlag] = useState(true);
  const [addingCategory, setAddingCategory] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState('');
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const categoryOptions = useMemo(
    () => Array.from(new Set([...PRESET_CATEGORIES, ...(stats?.categories ?? []), ...rules.map((rule) => rule.category)])),
    [rules, stats]
  );

  const categoryCounts = useMemo(() => rules.reduce<Record<string, number>>((acc, rule) => {
    acc[rule.category] = (acc[rule.category] ?? 0) + 1;
    return acc;
  }, {}), [rules]);

  const statusCounts = useMemo(() => {
    const scopedRules = filterCategory
      ? rules.filter((rule) => rule.category === filterCategory)
      : rules;

    return {
      all: scopedRules.length,
      active: scopedRules.filter((rule) => Boolean(rule.is_active)).length,
      inactive: scopedRules.filter((rule) => !rule.is_active).length,
    };
  }, [filterCategory, rules]);

  const visibleRules = useMemo(() => rules.filter((rule) => {
    const categoryMatched = !filterCategory || rule.category === filterCategory;
    const statusMatched =
      statusFilter === 'all'
        ? true
        : statusFilter === 'active'
          ? Boolean(rule.is_active)
          : !rule.is_active;

    return categoryMatched && statusMatched;
  }), [filterCategory, rules, statusFilter]);

  /** 加载规则列表和统计 */
  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [ruleList, statsData] = await Promise.all([
        listKnowhowRules(undefined, false),
        getKnowhowStats(),
      ]);
      setRules(ruleList);
      setStats(statsData);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  /** 确认重命名分类 */
  const handleRenameCategory = async () => {
    if (!renamingCat || !renameValue.trim()) return;
    try {
      await renameKnowhowCategory(renamingCat, renameValue.trim());
      if (filterCategory === renamingCat) setFilterCategory(renameValue.trim());
      setRenamingCat(null);
      setRenameValue('');
      await loadData();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  };

  /** 确认删除分类 */
  const handleDeleteCategory = async () => {
    if (!deletingCat) return;
    try {
      await deleteKnowhowCategory(deletingCat, deleteRules);
      if (filterCategory === deletingCat) setFilterCategory('');
      setDeletingCat(null);
      setDeleteRulesFlag(true);
      await loadData();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  };

  /** 确认新建分类（新建一条该分类的空规则编辑表单） */
  const handleAddCategory = () => {
    const name = newCategoryName.trim();
    if (!name) return;
    setAddingCategory(false);
    setNewCategoryName('');
    setEditingRule({ category: name, rule_text: '', weight: 1.0, source: 'manual' });
  };

  /** 保存规则（新建或更新） */
  const handleSave = async () => {
    if (!editingRule?.rule_text?.trim() || !editingRule?.category) return;
    try {
      if (editingRule.id) {
        await updateKnowhowRule(editingRule.id, {
          category: editingRule.category,
          rule_text: editingRule.rule_text,
          weight: editingRule.weight,
          is_active: editingRule.is_active,
        });
      } else {
        await createKnowhowRule({
          category: editingRule.category,
          rule_text: editingRule.rule_text,
          weight: editingRule.weight ?? 1.0,
          source: editingRule.source ?? 'manual',
        });
      }
      setEditingRule(null);
      await loadData();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  };

  /** 删除规则 */
  const handleDelete = async (ruleId: string) => {
    try {
      await deleteKnowhowRule(ruleId);
      await loadData();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  };

  /** 切换规则启用状态 */
  const handleToggleActive = async (rule: KnowhowRule) => {
    try {
      await updateKnowhowRule(rule.id, { is_active: rule.is_active ? 0 : 1 });
      await loadData();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  };

  /** 导出规则库 */
  const handleExport = async () => {
    setBusyAction('export');
    setError('');
    try {
      const data = await exportKnowhowRules();
      downloadKnowhowExport(data);
      setNotice(`已导出 ${data.total_rules} 条规则。`);
    } catch (e: unknown) {
      setNotice('');
      setError((e as Error).message);
    } finally {
      setBusyAction('');
    }
  };

  /** 选择导入文件 */
  const handleImportFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    setError('');
    setNotice('');

    try {
      const text = await file.text();
      const payload = JSON.parse(text) as unknown;
      const ruleCount = getImportRuleCount(payload);
      if (ruleCount <= 0) {
        throw new Error('导入文件中没有可识别的规则');
      }

      setImportStrategy('append');
      setPendingImport({ fileName: file.name, ruleCount, payload });
    } catch {
      setPendingImport(null);
      setError('导入文件不是有效的 Know-how JSON');
    }
  };

  /** 确认导入 */
  const handleConfirmImport = async () => {
    if (!pendingImport) return;

    setBusyAction('import');
    setError('');
    try {
      const result = await importKnowhowRules(pendingImport.payload, importStrategy);
      if (importStrategy === 'replace') {
        setFilterCategory('');
        setStatusFilter('all');
      }
      setPendingImport(null);
      setNotice(buildImportNotice(result));
      await loadData();
    } catch (e: unknown) {
      setNotice('');
      setError((e as Error).message);
    } finally {
      setBusyAction('');
    }
  };

  return (
    <div className={clsx('flex flex-col', standalone ? 'h-full' : 'max-h-[500px]')}>
      {/* 头部：标题 + 统计 + 新建规则 */}
      <div className="win-toolbar flex items-center justify-between px-4 py-3">
        <div>
          <h3 className="text-sm font-medium">Know-how 规则库</h3>
          {stats && (
            <p className="text-xs text-text-secondary mt-0.5">
              共 {stats.total_rules} 条规则，{stats.active_rules} 条启用
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={importInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={handleImportFileChange}
          />
          <button
            onClick={handleExport}
            disabled={busyAction === 'import' || busyAction === 'export'}
            className="win-button h-8 px-3 text-xs disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busyAction === 'export' ? '导出中...' : '导出'}
          </button>
          <button
            onClick={() => importInputRef.current?.click()}
            disabled={busyAction === 'import' || busyAction === 'export'}
            className="win-button h-8 px-3 text-xs disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busyAction === 'import' ? '导入中...' : '导入'}
          </button>
          <button
            onClick={() => setEditingRule({ category: categoryOptions[0] ?? '采购预审', rule_text: '', weight: 1.0, source: 'manual' })}
            className="win-button-primary h-8 px-3 text-xs"
          >
            + 新建规则
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mx-4 mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 underline">关闭</button>
        </div>
      )}

      {/* 成功提示 */}
      {notice && (
        <div className="mx-4 mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300">
          {notice}
          <button onClick={() => setNotice('')} className="ml-2 underline">关闭</button>
        </div>
      )}

      {/* 分类筛选行（含内联增删改） */}
      <div className="flex flex-wrap gap-2 overflow-x-auto border-b border-surface-divider px-4 py-2.5 scrollbar-thin dark:border-dark-divider">
        <FilterChip label="全部分类" active={!filterCategory} count={rules.length} onClick={() => setFilterCategory('')} />
        {categoryOptions.map((cat) => (
          <CategoryChip
            key={cat}
            label={cat}
            active={filterCategory === cat}
            count={categoryCounts[cat] ?? 0}
            onSelect={() => setFilterCategory(cat)}
            onRename={() => { setRenamingCat(cat); setRenameValue(cat); }}
            onDelete={() => { setDeletingCat(cat); setDeleteRulesFlag(true); }}
          />
        ))}
        {/* 新建分类 */}
        {addingCategory ? (
          <div className="flex items-center gap-1.5">
            <input
              autoFocus
              value={newCategoryName}
              onChange={(e) => setNewCategoryName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAddCategory(); if (e.key === 'Escape') { setAddingCategory(false); setNewCategoryName(''); } }}
              className="win-input w-28 !py-1 text-xs"
              placeholder="分类名称"
            />
            <button onClick={handleAddCategory} disabled={!newCategoryName.trim()} className="win-icon-button h-7 w-7 text-xs disabled:opacity-40">✓</button>
            <button onClick={() => { setAddingCategory(false); setNewCategoryName(''); }} className="win-icon-button h-7 w-7 text-xs">✕</button>
          </div>
        ) : (
          <button
            onClick={() => setAddingCategory(true)}
            className="win-chip text-xs"
          >
            + 新建分类
          </button>
        )}
      </div>

      {/* 启用状态筛选 */}
      <div className="flex gap-2 overflow-x-auto border-b border-surface-divider px-4 py-2.5 scrollbar-thin dark:border-dark-divider">
        <FilterChip label="全部" active={statusFilter === 'all'} count={statusCounts.all} onClick={() => setStatusFilter('all')} />
        <FilterChip label="已启用" active={statusFilter === 'active'} count={statusCounts.active} onClick={() => setStatusFilter('active')} />
        <FilterChip label="已停用" active={statusFilter === 'inactive'} count={statusCounts.inactive} onClick={() => setStatusFilter('inactive')} />
      </div>

      {/* 编辑表单 */}
      {editingRule && (
        <RuleForm rule={editingRule} onSave={handleSave}
          onCancel={() => setEditingRule(null)} onChange={setEditingRule} />
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin bg-[#F7F8FA] p-4 space-y-2 dark:bg-dark">
        {loading ? (
          <div className="text-center py-8 text-sm text-text-secondary">加载中...</div>
        ) : visibleRules.length === 0 ? (
          <div className="text-center py-8 text-sm text-text-secondary">
            <p>📋</p><p className="mt-2">当前筛选下暂无规则</p>
          </div>
        ) : (
          visibleRules.map((rule) => (
            <RuleCard key={rule.id} rule={rule}
              onEdit={() => setEditingRule(rule)}
              onDelete={() => handleDelete(rule.id)}
              onToggle={() => handleToggleActive(rule)} />
          ))
        )}
      </div>

      {/* 重命名分类对话框 */}
      {renamingCat && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setRenamingCat(null)}>
          <div className="win-modal w-80 p-5" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-medium mb-3">重命名分类</h4>
            <p className="text-xs text-text-secondary mb-3">将「{renamingCat}」重命名为：</p>
            <input
              autoFocus
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleRenameCategory()}
              className="win-input mb-4"
              placeholder="新分类名称"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setRenamingCat(null)} className="win-button h-8 px-3 text-xs">取消</button>
              <button onClick={handleRenameCategory} disabled={!renameValue.trim()} className="win-button-primary h-8 px-3 text-xs">确认重命名</button>
            </div>
          </div>
        </div>
      )}

      {/* 删除分类确认对话框 */}
      {deletingCat && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setDeletingCat(null)}>
          <div className="win-modal w-80 p-5" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-medium mb-3">删除分类「{deletingCat}」</h4>
            <p className="text-xs text-text-secondary mb-3">请选择如何处理该分类下的规则：</p>
            <div className="space-y-2 mb-4">
              <label className="flex items-start gap-2 cursor-pointer">
                <input type="radio" checked={deleteRules} onChange={() => setDeleteRulesFlag(true)} className="mt-0.5" />
                <div>
                  <p className="text-xs font-medium">同时删除该分类下的所有规则</p>
                  <p className="text-[10px] text-text-secondary">规则将被永久删除，无法恢复</p>
                </div>
              </label>
              <label className="flex items-start gap-2 cursor-pointer">
                <input type="radio" checked={!deleteRules} onChange={() => setDeleteRulesFlag(false)} className="mt-0.5" />
                <div>
                  <p className="text-xs font-medium">仅删除分类名，保留规则</p>
                  <p className="text-[10px] text-text-secondary">规则将移至"未分类"</p>
                </div>
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeletingCat(null)} className="win-button h-8 px-3 text-xs">取消</button>
              <button onClick={handleDeleteCategory} className="inline-flex h-8 items-center justify-center rounded-md bg-red-500 px-3 text-xs font-medium text-white shadow-sm transition-colors hover:bg-red-600">确认删除</button>
            </div>
          </div>
        </div>
      )}

      {/* 导入确认对话框 */}
      {pendingImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => busyAction !== 'import' && setPendingImport(null)}>
          <div className="win-modal w-96 p-5" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-medium mb-3">导入 Know-how 规则</h4>
            <p className="text-xs text-text-secondary mb-3">
              文件「{pendingImport.fileName}」中发现 {pendingImport.ruleCount} 条规则。
            </p>
            <div className="space-y-2 mb-4">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={importStrategy === 'append'}
                  onChange={() => setImportStrategy('append')}
                  className="mt-0.5"
                />
                <div>
                  <p className="text-xs font-medium">追加导入</p>
                  <p className="text-[10px] text-text-secondary">保留现有规则，已存在的同分类同内容规则会自动跳过。</p>
                </div>
              </label>
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={importStrategy === 'replace'}
                  onChange={() => setImportStrategy('replace')}
                  className="mt-0.5"
                />
                <div>
                  <p className="text-xs font-medium">覆盖导入</p>
                  <p className="text-[10px] text-text-secondary">先清空当前规则库，再按这个文件重建。</p>
                </div>
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setPendingImport(null)}
                disabled={busyAction === 'import'}
                className="win-button h-8 px-3 text-xs disabled:opacity-60"
              >
                取消
              </button>
              <button
                onClick={handleConfirmImport}
                disabled={busyAction === 'import'}
                className="win-button-primary h-8 px-3 text-xs disabled:opacity-60"
              >
                {busyAction === 'import' ? '导入中...' : '开始导入'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 分类筛选标签（无操作按钮，用于"全部"和状态筛选） */
function FilterChip({ label, active, count, onClick }: {
  label: string; active: boolean; count?: number; onClick: () => void;
}) {
  return (
    <button onClick={onClick} className={clsx(
      'inline-flex items-center rounded-md border px-2.5 py-1.5 text-xs whitespace-nowrap shadow-sm transition-colors',
      active
        ? 'border-primary/20 bg-primary text-white'
        : 'border-surface-divider bg-white text-text-secondary hover:border-primary/20 hover:text-text-primary dark:border-dark-divider dark:bg-dark-card dark:hover:border-primary/20 dark:hover:text-text-dark-primary',
    )}>
      {label}{count !== undefined && ` (${count})`}
    </button>
  );
}

/** 分类 Chip（带内联重命名 / 删除图标，hover 时显示） */
function CategoryChip({ label, active, count, onSelect, onRename, onDelete }: {
  label: string; active: boolean; count?: number;
  onSelect: () => void; onRename: () => void; onDelete: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      className="relative flex items-center"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        onClick={onSelect}
        className={clsx(
          'inline-flex items-center rounded-md border px-2.5 py-1.5 pr-1 text-xs whitespace-nowrap shadow-sm transition-colors',
          active
            ? 'border-primary/20 bg-primary text-white'
            : 'border-surface-divider bg-white text-text-secondary hover:border-primary/20 hover:text-text-primary dark:border-dark-divider dark:bg-dark-card dark:hover:border-primary/20 dark:hover:text-text-dark-primary',
        )}
      >
        {label}{count !== undefined && ` (${count})`}
      </button>
      {hovered && (
        <div className="flex items-center ml-0.5 gap-0.5">
          <button
            onClick={(e) => { e.stopPropagation(); onRename(); }}
            className="win-icon-button h-6 w-6 text-[10px]"
            title="重命名"
          >✏️</button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="win-icon-button h-6 w-6 text-[10px]"
            title="删除分类"
          >🗑️</button>
        </div>
      )}
    </div>
  );
}

/** 规则编辑表单 */
function RuleForm({ rule, onSave, onCancel, onChange }: {
  rule: Partial<KnowhowRule>;
  onSave: () => void;
  onCancel: () => void;
  onChange: (r: Partial<KnowhowRule>) => void;
}) {
  return (
    <div className="win-panel mx-4 mt-3 space-y-3 p-4">
      <div className="flex gap-2">
        <select value={rule.category || ''} onChange={(e) => onChange({ ...rule, category: e.target.value })}
          className="win-select flex-1 !py-1.5 text-xs">
          {PRESET_CATEGORIES.map((cat) => <option key={cat} value={cat}>{cat}</option>)}
        </select>
        <input type="number" value={rule.weight ?? 1.0} min={0} max={5} step={0.1}
          onChange={(e) => onChange({ ...rule, weight: parseFloat(e.target.value) })}
          className="win-input w-20 !py-1.5 text-xs"
          placeholder="权重" />
      </div>
      <textarea value={rule.rule_text || ''} onChange={(e) => onChange({ ...rule, rule_text: e.target.value })}
        className="win-input w-full resize-none text-sm leading-6"
        rows={3} placeholder="输入规则内容..." />
      <div className="flex gap-2 justify-end">
        <button onClick={onCancel} className="win-button h-8 px-3 text-xs">
          取消
        </button>
        <button onClick={onSave} disabled={!rule.rule_text?.trim()}
          className="win-button-primary h-8 px-3 text-xs">
          {rule.id ? '更新' : '创建'}
        </button>
      </div>
    </div>
  );
}

/** 规则卡片 */
function RuleCard({ rule, onEdit, onDelete, onToggle }: {
  rule: KnowhowRule; onEdit: () => void; onDelete: () => void; onToggle: () => void;
}) {
  return (
    <div className={clsx(
      'rounded-lg border bg-white p-3 shadow-sm transition-colors dark:bg-dark-card',
      rule.is_active
        ? 'border-surface-divider dark:border-dark-divider'
        : 'border-dashed border-gray-300 dark:border-gray-600 opacity-60',
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="win-badge border-blue-200 bg-blue-50 text-[10px] text-blue-600 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400">
              {rule.category}
            </span>
            <span className="text-[10px] text-text-secondary">权重: {rule.weight}</span>
            {!rule.is_active && (
              <span className="text-[10px] text-amber-600 dark:text-amber-400">已停用</span>
            )}
            {rule.hit_count > 0 && (
              <span className="text-[10px] text-text-secondary">命中: {rule.hit_count}</span>
            )}
          </div>
          <p className="text-sm leading-relaxed">{rule.rule_text}</p>
          <p className="text-[10px] text-text-secondary mt-1">
            来源: {rule.source} · {new Date(rule.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button onClick={onToggle} title={rule.is_active ? '禁用' : '启用'}
            className="win-icon-button h-8 w-8 text-xs">
            {rule.is_active ? '🟢' : '⚪'}
          </button>
          <button onClick={onEdit} title="编辑"
            className="win-icon-button h-8 w-8 text-xs">
            ✏️
          </button>
          <button onClick={onDelete} title="删除"
            className="win-icon-button h-8 w-8 text-xs">
            🗑️
          </button>
        </div>
      </div>
    </div>
  );
}
