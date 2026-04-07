import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import clsx from 'clsx';

import { useAuthStore } from '@/stores/authStore';
import {
  createKnowhowCategory,
  createKnowhowRule,
  deleteKnowhowCategory,
  deleteKnowhowRule,
  exportKnowhowRules,
  getKnowhowStats,
  importKnowhowRules,
  listKnowhowCategories,
  listKnowhowRules,
  renameKnowhowCategory,
  updateKnowhowRule,
} from '@/services/api';
import { emitAppDataInvalidation } from '@/utils/appInvalidation';
import type {
  KnowhowCategory,
  KnowhowExportData,
  KnowhowImportStrategy,
  KnowhowRule,
} from '@/types';

type RuleStatusFilter = 'all' | 'active' | 'inactive';

interface Props {
  standalone?: boolean;
}

function getImportRuleCount(payload: unknown): number {
  if (Array.isArray(payload)) return payload.length;
  if (payload && typeof payload === 'object' && Array.isArray((payload as { rules?: unknown[] }).rules)) {
    return (payload as { rules: unknown[] }).rules.length;
  }
  return 0;
}

function downloadKnowhowExport(data: KnowhowExportData) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
  const exportDate = data.exported_at?.slice(0, 10) || new Date().toISOString().slice(0, 10);
  const fileName = `knowhow-rules-${exportDate}.json`;
  const legacyNavigator = window.navigator as Navigator & {
    msSaveBlob?: (blob: Blob, defaultName?: string) => boolean;
    msSaveOrOpenBlob?: (blob: Blob, defaultName?: string) => boolean;
  };

  if (typeof legacyNavigator.msSaveOrOpenBlob === 'function') {
    legacyNavigator.msSaveOrOpenBlob(blob, fileName);
    return;
  }

  if (typeof legacyNavigator.msSaveBlob === 'function') {
    legacyNavigator.msSaveBlob(blob, fileName);
    return;
  }

  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
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
  const action = result.strategy === 'replace'
    ? `已覆盖导入，并先清空 ${result.deleted_count} 条旧规则。`
    : '已追加导入。';
  const skipped = result.skipped_count > 0 ? `跳过重复 ${result.skipped_count} 条。` : '';
  return `${action} 本次读取 ${result.total_in_file} 条，成功导入 ${result.imported_count} 条。${skipped} 当前共有 ${result.total_after_import} 条规则。`;
}

function getRuleOwnershipLabel(rule: KnowhowRule): string {
  return rule.owner_group_id ? '本组共享' : '个人规则';
}

export default function KnowhowManager({ standalone = true }: Props) {
  const user = useAuthStore((state) => state.user);
  const userIsAdmin = user?.system_role === 'admin';
  const userCanManageGroupKnowhow = Boolean(user?.group_id && user?.can_manage_group_knowhow);
  const allowGroupSharing = !userIsAdmin && userCanManageGroupKnowhow;
  const canManageLibrary = userIsAdmin || userCanManageGroupKnowhow;

  const [rules, setRules] = useState<KnowhowRule[]>([]);
  const [stats, setStats] = useState<{ total_rules: number; active_rules: number; categories: string[]; total_hits: number } | null>(null);
  const [categories, setCategories] = useState<KnowhowCategory[]>([]);
  const [filterCategory, setFilterCategory] = useState('');
  const [statusFilter, setStatusFilter] = useState<RuleStatusFilter>('all');
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<'import' | 'export' | ''>('');
  const [editingRule, setEditingRule] = useState<Partial<KnowhowRule> | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [addingCategory, setAddingCategory] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [renamingCategory, setRenamingCategory] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [deletingCategory, setDeletingCategory] = useState('');
  const [deleteRules, setDeleteRules] = useState(true);
  const [pendingImport, setPendingImport] = useState<{ fileName: string; ruleCount: number; payload: unknown } | null>(null);
  const [importStrategy, setImportStrategy] = useState<KnowhowImportStrategy>('append');
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const categoryOptions = useMemo(
    () => Array.from(new Set([
      ...categories.map((category) => category.name),
      ...rules.map((rule) => rule.category),
      ...(editingRule?.category ? [editingRule.category] : []),
    ].filter(Boolean))),
    [categories, editingRule?.category, rules],
  );

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

  const categoryCounts = useMemo(() => {
    const counts = rules.reduce<Record<string, number>>((acc, rule) => {
      acc[rule.category] = (acc[rule.category] ?? 0) + 1;
      return acc;
    }, {});
    for (const category of categories) {
      counts[category.name] = counts[category.name] ?? category.rule_count ?? 0;
    }
    return counts;
  }, [categories, rules]);

  const canManageRule = useCallback((rule: KnowhowRule) => {
    if (userIsAdmin) return true;
    if (!user?.id) return false;
    if (rule.owner_group_id) {
      return Boolean(userCanManageGroupKnowhow && user.group_id === rule.owner_group_id);
    }
    return rule.owner_id === user.id;
  }, [user?.group_id, user?.id, userCanManageGroupKnowhow, userIsAdmin]);

  const canManageCategory = useCallback((name: string) => {
    const category = categories.find((item) => item.name === name);
    return Boolean(category?.can_manage);
  }, [categories]);

  const openCreateRule = useCallback(() => {
    setEditingRule({
      category: categoryOptions[0] ?? '采购预审',
      rule_text: '',
      weight: 1.0,
      source: 'manual',
      share_to_group: false,
    });
  }, [categoryOptions]);

  const openEditRule = useCallback((rule: KnowhowRule) => {
    setEditingRule({
      ...rule,
      share_to_group: Boolean(allowGroupSharing && user?.group_id && rule.owner_group_id === user.group_id),
    });
  }, [allowGroupSharing, user?.group_id]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [ruleList, statsData, categoryList] = await Promise.all([
        listKnowhowRules(undefined, false),
        getKnowhowStats(),
        listKnowhowCategories(),
      ]);
      setRules(ruleList);
      setStats(statsData);
      setCategories(categoryList);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleSave = useCallback(async () => {
    if (!editingRule?.rule_text?.trim() || !editingRule.category) return;
    try {
      if (editingRule.id) {
        await updateKnowhowRule(editingRule.id, {
          category: editingRule.category,
          rule_text: editingRule.rule_text,
          weight: editingRule.weight,
          is_active: editingRule.is_active,
          share_to_group: allowGroupSharing ? Boolean(editingRule.share_to_group) : undefined,
        });
      } else {
        await createKnowhowRule({
          category: editingRule.category,
          rule_text: editingRule.rule_text,
          weight: editingRule.weight ?? 1.0,
          source: editingRule.source ?? 'manual',
          share_to_group: allowGroupSharing ? Boolean(editingRule.share_to_group) : undefined,
        });
      }
      setEditingRule(null);
      await loadData();
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [allowGroupSharing, editingRule, loadData]);

  const handleDeleteRule = useCallback(async (ruleId: string) => {
    try {
      await deleteKnowhowRule(ruleId);
      await loadData();
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [loadData]);

  const handleToggleRule = useCallback(async (rule: KnowhowRule) => {
    try {
      await updateKnowhowRule(rule.id, { is_active: rule.is_active ? 0 : 1 });
      await loadData();
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [loadData]);

  const handleAddCategory = useCallback(async () => {
    const name = newCategoryName.trim();
    if (!name) return;
    try {
      await createKnowhowCategory(name);
      setAddingCategory(false);
      setNewCategoryName('');
      setFilterCategory(name);
      setNotice(`分类“${name}”已创建`);
      await loadData();
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [loadData, newCategoryName]);

  const handleRenameCategory = useCallback(async () => {
    const nextName = renameValue.trim();
    if (!renamingCategory || !nextName) return;
    try {
      await renameKnowhowCategory(renamingCategory, nextName);
      if (filterCategory === renamingCategory) setFilterCategory(nextName);
      setNotice(`分类“${renamingCategory}”已重命名为“${nextName}”`);
      setRenamingCategory('');
      setRenameValue('');
      await loadData();
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [filterCategory, loadData, renameValue, renamingCategory]);

  const handleDeleteCategory = useCallback(async () => {
    if (!deletingCategory) return;
    try {
      await deleteKnowhowCategory(deletingCategory, deleteRules);
      if (filterCategory === deletingCategory) setFilterCategory('');
      setDeletingCategory('');
      setDeleteRules(true);
      await loadData();
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [deleteRules, deletingCategory, filterCategory, loadData]);

  const handleExport = useCallback(async () => {
    setBusyAction('export');
    setError('');
    try {
      const data = await exportKnowhowRules();
      downloadKnowhowExport(data);
      setNotice(`已导出 ${data.total_rules} 条规则。`);
    } catch (err) {
      setNotice('');
      setError((err as Error).message);
    } finally {
      setBusyAction('');
    }
  }, []);

  const handleImportFileChange = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
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
        throw new Error('导入文件中没有可识别的规则。');
      }
      setImportStrategy('append');
      setPendingImport({ fileName: file.name, ruleCount, payload });
    } catch {
      setPendingImport(null);
      setError('导入文件不是有效的 Know-how JSON。');
    }
  }, []);

  const handleConfirmImport = useCallback(async () => {
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
      emitAppDataInvalidation(['knowhow']);
    } catch (err) {
      setNotice('');
      setError((err as Error).message);
    } finally {
      setBusyAction('');
    }
  }, [importStrategy, loadData, pendingImport]);

  return (
    <div className={clsx('flex flex-col', standalone ? 'h-full' : 'max-h-[500px]')}>
      <div className="win-toolbar flex items-center justify-between px-4 py-3">
        <div>
          <h3 className="text-sm font-medium">Know-how 规则库</h3>
          {stats && (
            <p className="mt-0.5 text-xs text-text-secondary">
              共 {stats.total_rules} 条规则，启用 {stats.active_rules} 条
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={importInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(event) => void handleImportFileChange(event)}
          />
          <button
            onClick={() => void handleExport()}
            disabled={!canManageLibrary || busyAction !== ''}
            className="win-button h-8 px-3 text-xs disabled:cursor-not-allowed disabled:opacity-60"
            title={userIsAdmin ? '导出全部规则库' : '导出本组规则库'}
          >
            {busyAction === 'export' ? '导出中...' : '导出'}
          </button>
          <button
            onClick={() => importInputRef.current?.click()}
            disabled={!canManageLibrary || busyAction !== ''}
            className="win-button h-8 px-3 text-xs disabled:cursor-not-allowed disabled:opacity-60"
            title={userIsAdmin ? '导入规则库' : '导入到本组规则库'}
          >
            {busyAction === 'import' ? '导入中...' : '导入'}
          </button>
          <button onClick={openCreateRule} className="win-button-primary h-8 px-3 text-xs">
            + 新建规则
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
          {error}
          <button onClick={() => setError('')} className="ml-2 underline">关闭</button>
        </div>
      )}

      {notice && (
        <div className="mx-4 mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {notice}
          <button onClick={() => setNotice('')} className="ml-2 underline">关闭</button>
        </div>
      )}

      <div className="flex flex-wrap gap-2 overflow-x-auto border-b border-surface-divider px-4 py-2.5 scrollbar-thin dark:border-dark-divider">
        <FilterChip
          label="全部分类"
          active={!filterCategory}
          count={rules.length}
          onClick={() => setFilterCategory('')}
        />
        {categoryOptions.map((categoryName) => (
          <CategoryChip
            key={categoryName}
            label={categoryName}
            active={filterCategory === categoryName}
            count={categoryCounts[categoryName] ?? 0}
            onSelect={() => setFilterCategory(categoryName)}
            onRename={() => {
              setRenamingCategory(categoryName);
              setRenameValue(categoryName);
            }}
            onDelete={() => {
              setDeletingCategory(categoryName);
              setDeleteRules(true);
            }}
            canManage={canManageCategory(categoryName)}
          />
        ))}
        {canManageLibrary && addingCategory ? (
          <div className="flex items-center gap-1.5">
            <input
              autoFocus
              value={newCategoryName}
              onChange={(event) => setNewCategoryName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleAddCategory();
                if (event.key === 'Escape') {
                  setAddingCategory(false);
                  setNewCategoryName('');
                }
              }}
              className="win-input w-32 !py-1 text-xs"
              placeholder="分类名称"
            />
            <button
              onClick={() => void handleAddCategory()}
              disabled={!newCategoryName.trim()}
              className="win-icon-button h-7 w-7 text-xs disabled:opacity-40"
            >
              确认
            </button>
            <button
              onClick={() => {
                setAddingCategory(false);
                setNewCategoryName('');
              }}
              className="win-icon-button h-7 w-7 text-xs"
            >
              取消
            </button>
          </div>
        ) : canManageLibrary ? (
          <button onClick={() => setAddingCategory(true)} className="win-chip text-xs">
            + 新建分类
          </button>
        ) : null}
      </div>

      <div className="flex gap-2 overflow-x-auto border-b border-surface-divider px-4 py-2.5 scrollbar-thin dark:border-dark-divider">
        <FilterChip label="全部" active={statusFilter === 'all'} count={statusCounts.all} onClick={() => setStatusFilter('all')} />
        <FilterChip label="已启用" active={statusFilter === 'active'} count={statusCounts.active} onClick={() => setStatusFilter('active')} />
        <FilterChip label="已停用" active={statusFilter === 'inactive'} count={statusCounts.inactive} onClick={() => setStatusFilter('inactive')} />
      </div>

      {editingRule && (
        <RuleForm
          rule={editingRule}
          onSave={() => void handleSave()}
          onCancel={() => setEditingRule(null)}
          onChange={setEditingRule}
          categoryOptions={categoryOptions}
          allowGroupSharing={allowGroupSharing}
        />
      )}

      <div className="flex-1 space-y-2 overflow-y-auto bg-[#F7F8FA] p-4 scrollbar-thin dark:bg-dark">
        {loading ? (
          <div className="py-8 text-center text-sm text-text-secondary">加载中...</div>
        ) : visibleRules.length === 0 ? (
          <div className="py-8 text-center text-sm text-text-secondary">当前筛选下暂无规则</div>
        ) : (
          visibleRules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              ownershipLabel={getRuleOwnershipLabel(rule)}
              isGroupShared={Boolean(rule.owner_group_id)}
              onEdit={() => openEditRule(rule)}
              onDelete={() => void handleDeleteRule(rule.id)}
              onToggle={() => void handleToggleRule(rule)}
              canManage={canManageRule(rule)}
            />
          ))
        )}
      </div>

      {renamingCategory && (
        <Modal onClose={() => setRenamingCategory('')}>
          <h4 className="mb-3 text-sm font-medium">重命名分类</h4>
          <p className="mb-3 text-xs text-text-secondary">把“{renamingCategory}”改成：</p>
          <input
            autoFocus
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void handleRenameCategory(); }}
            className="win-input mb-4"
            placeholder="新分类名称"
          />
          <div className="flex justify-end gap-2">
            <button onClick={() => setRenamingCategory('')} className="win-button h-8 px-3 text-xs">取消</button>
            <button onClick={() => void handleRenameCategory()} disabled={!renameValue.trim()} className="win-button-primary h-8 px-3 text-xs">确认</button>
          </div>
        </Modal>
      )}

      {deletingCategory && (
        <Modal onClose={() => setDeletingCategory('')}>
          <h4 className="mb-3 text-sm font-medium">删除分类“{deletingCategory}”</h4>
          <p className="mb-3 text-xs text-text-secondary">请选择如何处理该分类下的规则：</p>
          <div className="mb-4 space-y-2">
            <label className="flex cursor-pointer items-start gap-2">
              <input type="radio" checked={deleteRules} onChange={() => setDeleteRules(true)} className="mt-0.5" />
              <div>
                <p className="text-xs font-medium">同时删除该分类下的可管理规则</p>
                <p className="text-[10px] text-text-secondary">管理员会删除全量规则，组内 manager 只影响本组规则。</p>
              </div>
            </label>
            <label className="flex cursor-pointer items-start gap-2">
              <input type="radio" checked={!deleteRules} onChange={() => setDeleteRules(false)} className="mt-0.5" />
              <div>
                <p className="text-xs font-medium">只删除分类名，保留规则</p>
                <p className="text-[10px] text-text-secondary">保留的规则会被移到“未分类”。</p>
              </div>
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setDeletingCategory('')} className="win-button h-8 px-3 text-xs">取消</button>
            <button onClick={() => void handleDeleteCategory()} className="inline-flex h-8 items-center justify-center rounded-md bg-red-500 px-3 text-xs font-medium text-white shadow-sm transition-colors hover:bg-red-600">
              确认删除
            </button>
          </div>
        </Modal>
      )}

      {pendingImport && (
        <Modal onClose={() => { if (busyAction !== 'import') setPendingImport(null); }} widthClassName="w-96">
          <h4 className="mb-3 text-sm font-medium">导入 Know-how 规则</h4>
          <p className="mb-3 text-xs text-text-secondary">
            文件“{pendingImport.fileName}”中发现 {pendingImport.ruleCount} 条规则。
          </p>
          <div className="mb-4 space-y-2">
            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="radio"
                checked={importStrategy === 'append'}
                onChange={() => setImportStrategy('append')}
                className="mt-0.5"
              />
              <div>
                <p className="text-xs font-medium">追加导入</p>
                <p className="text-[10px] text-text-secondary">保留现有规则，只导入当前作用域内未重复的规则。</p>
              </div>
            </label>
            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="radio"
                checked={importStrategy === 'replace'}
                onChange={() => setImportStrategy('replace')}
                className="mt-0.5"
                disabled={!userIsAdmin}
              />
              <div>
                <p className="text-xs font-medium">覆盖导入</p>
                <p className="text-[10px] text-text-secondary">
                  仅管理员可用，会先清空当前规则库再重建。
                </p>
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
              onClick={() => void handleConfirmImport()}
              disabled={busyAction === 'import'}
              className="win-button-primary h-8 px-3 text-xs disabled:opacity-60"
            >
              {busyAction === 'import' ? '导入中...' : '开始导入'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function FilterChip({ label, active, count, onClick }: {
  label: string;
  active: boolean;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'inline-flex items-center rounded-md border px-2.5 py-1.5 text-xs whitespace-nowrap shadow-sm transition-colors',
        active
          ? 'border-primary/20 bg-primary text-white'
          : 'border-surface-divider bg-white text-text-secondary hover:border-primary/20 hover:text-text-primary dark:border-dark-divider dark:bg-dark-card dark:hover:border-primary/20 dark:hover:text-text-dark-primary',
      )}
    >
      {label}{count !== undefined && ` (${count})`}
    </button>
  );
}

function CategoryChip({ label, active, count, onSelect, onRename, onDelete, canManage }: {
  label: string;
  active: boolean;
  count?: number;
  onSelect: () => void;
  onRename: () => void;
  onDelete: () => void;
  canManage: boolean;
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
      {hovered && canManage && (
        <div className="ml-0.5 flex items-center gap-0.5">
          <button onClick={(event) => { event.stopPropagation(); onRename(); }} className="win-icon-button h-6 w-6 text-[10px]" title="重命名">
            改
          </button>
          <button onClick={(event) => { event.stopPropagation(); onDelete(); }} className="win-icon-button h-6 w-6 text-[10px]" title="删除分类">
            删
          </button>
        </div>
      )}
    </div>
  );
}

function RuleForm({ rule, onSave, onCancel, onChange, categoryOptions, allowGroupSharing }: {
  rule: Partial<KnowhowRule>;
  onSave: () => void;
  onCancel: () => void;
  onChange: (nextRule: Partial<KnowhowRule>) => void;
  categoryOptions: string[];
  allowGroupSharing: boolean;
}) {
  return (
    <div className="win-panel mx-4 mt-3 space-y-3 p-4">
      <div className="flex gap-2">
        <div className="flex-1">
          <input
            list="knowhow-category-options"
            value={rule.category || ''}
            onChange={(event) => onChange({ ...rule, category: event.target.value })}
            className="win-input w-full !py-1.5 text-xs"
            placeholder="输入或选择分类"
          />
          <datalist id="knowhow-category-options">
            {categoryOptions.map((category) => <option key={category} value={category} />)}
          </datalist>
        </div>
        <input
          type="number"
          value={rule.weight ?? 1.0}
          min={0}
          max={5}
          step={0.1}
          onChange={(event) => onChange({ ...rule, weight: parseFloat(event.target.value) })}
          className="win-input w-20 !py-1.5 text-xs"
          placeholder="权重"
        />
      </div>
      <textarea
        value={rule.rule_text || ''}
        onChange={(event) => onChange({ ...rule, rule_text: event.target.value })}
        className="win-input w-full resize-none text-sm leading-6"
        rows={3}
        placeholder="输入规则内容..."
      />
      {allowGroupSharing && (
        <label className="flex items-center gap-2 rounded-md border border-surface-divider bg-surface px-3 py-2 text-xs text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar">
          <input
            type="checkbox"
            checked={Boolean(rule.share_to_group)}
            onChange={(event) => onChange({ ...rule, share_to_group: event.target.checked })}
          />
          <span>共享给本组成员使用</span>
        </label>
      )}
      <p className="text-[11px] leading-5 text-text-secondary">
        系统会自动提炼关键词、适用场景和示例问法，你只需要把规则内容写清楚。
      </p>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="win-button h-8 px-3 text-xs">取消</button>
        <button onClick={onSave} disabled={!rule.rule_text?.trim() || !rule.category?.trim()} className="win-button-primary h-8 px-3 text-xs">
          {rule.id ? '更新' : '创建'}
        </button>
      </div>
    </div>
  );
}

function RuleCard({ rule, ownershipLabel, isGroupShared, onEdit, onDelete, onToggle, canManage }: {
  rule: KnowhowRule;
  ownershipLabel: string;
  isGroupShared: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
  canManage: boolean;
}) {
  const ownershipChipClassName = isGroupShared
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300'
    : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300';
  const ownershipAccentClassName = isGroupShared
    ? 'before:bg-emerald-400'
    : 'before:bg-amber-400';
  const ownershipHint = isGroupShared ? '本组成员可见可用' : '仅当前创建者可见';

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-lg border bg-white p-3 pl-4 shadow-sm transition-colors before:absolute before:bottom-0 before:left-0 before:top-0 before:w-1 dark:bg-dark-card',
        ownershipAccentClassName,
        rule.is_active
          ? 'border-surface-divider dark:border-dark-divider'
          : 'border-dashed border-gray-300 opacity-60 dark:border-gray-600',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <span className="win-badge border-blue-200 bg-blue-50 text-[10px] text-blue-600 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400">
              {rule.category}
            </span>
            <span className="text-[10px] text-text-secondary">权重: {rule.weight}</span>
            <span className={clsx('inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium', ownershipChipClassName)}>
              {ownershipLabel}
            </span>
            {!rule.is_active && <span className="text-[10px] text-amber-600 dark:text-amber-400">已停用</span>}
            {rule.hit_count > 0 && <span className="text-[10px] text-text-secondary">命中: {rule.hit_count}</span>}
          </div>
          <p className="mb-2 text-[11px] font-medium text-text-secondary">{ownershipHint}</p>
          <p className="text-sm leading-relaxed">{rule.rule_text}</p>
          <p className="mt-1 text-[10px] text-text-secondary">
            来源: {rule.source} | {new Date(rule.created_at).toLocaleDateString()}
          </p>
        </div>
        {canManage && (
          <div className="flex flex-shrink-0 items-center gap-1">
            <button onClick={onToggle} title={rule.is_active ? '停用' : '启用'} className="win-icon-button h-8 w-8 text-xs">
              {rule.is_active ? '停' : '启'}
            </button>
            <button onClick={onEdit} title="编辑" className="win-icon-button h-8 w-8 text-xs">改</button>
            <button onClick={onDelete} title="删除" className="win-icon-button h-8 w-8 text-xs">删</button>
          </div>
        )}
      </div>
    </div>
  );
}

function Modal({ children, onClose, widthClassName = 'w-80' }: {
  children: ReactNode;
  onClose: () => void;
  widthClassName?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className={clsx('win-modal p-5', widthClassName)} onClick={(event) => event.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
