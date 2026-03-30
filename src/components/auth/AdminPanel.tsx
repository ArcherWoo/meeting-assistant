/**
 * 管理员面板 - 用户、用户组和资源授权管理
 */
import { useState, useEffect, useCallback } from 'react';
import type { User, Group, AccessGrant, Role, SkillMeta } from '@/types';
import {
  listUsers, registerUser, deleteUser, updateUser,
  listGroups, createGroup, deleteGroup,
  listGrants, setGrant, removeGrant,
  listRoles, listSkills, listKnowledgeImports, listKnowhowRules,
} from '@/services/api';

type Tab = 'users' | 'groups' | 'grants';
type Toast = { msg: string; ok: boolean };

function useToast() {
  const [toast, setToastState] = useState<Toast | null>(null);
  const showToast = (msg: string, ok = true) => {
    setToastState({ msg, ok });
    setTimeout(() => setToastState(null), 3000);
  };
  return { toast, showToast };
}

export default function AdminPanel() {
  const [tab, setTab] = useState<Tab>('users');
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { toast, showToast } = useToast();

  // 新建用户表单
  const [showAddUser, setShowAddUser] = useState(false);
  const [newUser, setNewUser] = useState({ username: '', display_name: '', password: '', system_role: 'user', group_id: '' });

  // 新建用户组表单
  const [showAddGroup, setShowAddGroup] = useState(false);
  const [newGroup, setNewGroup] = useState({ name: '', description: '' });

  const refresh = useCallback(async () => {
    try {
      const [u, g] = await Promise.all([listUsers(), listGroups()]);
      setUsers(u);
      setGroups(g);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const handleAddUser = async () => {
    setLoading(true);
    try {
      await registerUser({ ...newUser, group_id: newUser.group_id || undefined });
      setShowAddUser(false);
      setNewUser({ username: '', display_name: '', password: '', system_role: 'user', group_id: '' });
      await refresh();
      showToast('用户创建成功');
    } catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const handleDeleteUser = async (id: string) => {
    if (!confirm('确定删除此用户？')) return;
    setLoading(true);
    try { await deleteUser(id); await refresh(); showToast('用户已删除'); }
    catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const handleToggleRole = async (u: User) => {
    setLoading(true);
    try {
      const newRole = u.system_role === 'admin' ? 'user' : 'admin';
      await updateUser(u.id, { system_role: newRole });
      await refresh();
      showToast(`已${newRole === 'admin' ? '升为管理员' : '降为普通用户'}`);
    } catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const handleAddGroup = async () => {
    setLoading(true);
    try {
      await createGroup(newGroup.name, newGroup.description);
      setShowAddGroup(false);
      setNewGroup({ name: '', description: '' });
      await refresh();
      showToast('用户组创建成功');
    } catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const handleDeleteGroup = async (id: string) => {
    if (!confirm('确定删除此用户组？')) return;
    setLoading(true);
    try { await deleteGroup(id); await refresh(); showToast('用户组已删除'); }
    catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const inputCls = 'w-full rounded-md border border-surface-divider bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-primary';

  return (
    <div className="flex-1 overflow-y-auto p-6 relative">
      <h1 className="text-lg font-semibold text-text-primary dark:text-text-dark-primary mb-4">用户管理</h1>

      {/* Toast 提示 */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 rounded-md px-4 py-2 text-sm text-white shadow-lg transition-all ${
          toast.ok ? 'bg-green-500' : 'bg-red-500'
        }`}>
          {toast.msg}
        </div>
      )}

      {/* 加载遮罩 */}
      {loading && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-white/50 dark:bg-dark-card/50">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 underline">关闭</button>
        </div>
      )}

      {/* Tab 切换 */}
      <div className="flex gap-1 mb-4 rounded-md border border-surface-divider bg-surface p-1 dark:border-dark-divider dark:bg-dark-sidebar w-fit">
        {([['users', '用户'], ['groups', '用户组'], ['grants', '资源授权']] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`rounded-md px-4 py-1.5 text-sm transition-colors ${
              tab === key
                ? 'bg-white text-primary shadow-sm dark:bg-dark-card'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'users' && (
        <div className="space-y-3">
          <button onClick={() => setShowAddUser(!showAddUser)} className="win-button-primary px-4 py-2 text-sm">
            {showAddUser ? '取消' : '+ 添加用户'}
          </button>

          {showAddUser && (
            <div className="rounded-lg border border-surface-divider bg-white p-4 dark:border-dark-divider dark:bg-dark-card space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <input className={inputCls} placeholder="用户名" value={newUser.username} onChange={e => setNewUser({ ...newUser, username: e.target.value })} />
                <input className={inputCls} placeholder="显示名" value={newUser.display_name} onChange={e => setNewUser({ ...newUser, display_name: e.target.value })} />
                <input className={inputCls} type="password" placeholder="密码" value={newUser.password} onChange={e => setNewUser({ ...newUser, password: e.target.value })} />
                <select className={inputCls} value={newUser.system_role} onChange={e => setNewUser({ ...newUser, system_role: e.target.value })}>
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
                <select className={inputCls} value={newUser.group_id} onChange={e => setNewUser({ ...newUser, group_id: e.target.value })}>
                  <option value="">无分组</option>
                  {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                </select>
              </div>
              <button onClick={() => void handleAddUser()} disabled={!newUser.username || !newUser.password || !newUser.display_name} className="win-button-primary px-4 py-2 text-sm disabled:opacity-50">
                创建
              </button>
            </div>
          )}

          <UserTable users={users} groups={groups} onDelete={handleDeleteUser} onToggleRole={handleToggleRole} />
        </div>
      )}

      {tab === 'groups' && (
        <div className="space-y-3">
          <button onClick={() => setShowAddGroup(!showAddGroup)} className="win-button-primary px-4 py-2 text-sm">
            {showAddGroup ? '取消' : '+ 添加用户组'}
          </button>

          {showAddGroup && (
            <div className="rounded-lg border border-surface-divider bg-white p-4 dark:border-dark-divider dark:bg-dark-card space-y-3">
              <input className={inputCls} placeholder="组名" value={newGroup.name} onChange={e => setNewGroup({ ...newGroup, name: e.target.value })} />
              <input className={inputCls} placeholder="描述（可选）" value={newGroup.description} onChange={e => setNewGroup({ ...newGroup, description: e.target.value })} />
              <button onClick={() => void handleAddGroup()} disabled={!newGroup.name} className="win-button-primary px-4 py-2 text-sm disabled:opacity-50">创建</button>
            </div>
          )}

          <GroupTable groups={groups} onDelete={handleDeleteGroup} />
        </div>
      )}

      {tab === 'grants' && (
        <GrantsTab users={users} groups={groups} />
      )}
    </div>
  );
}

function UserTable({ users, groups, onDelete, onToggleRole }: {
  users: User[];
  groups: Group[];
  onDelete: (id: string) => Promise<void>;
  onToggleRole: (u: User) => Promise<void>;
}) {
  const getGroupName = (gid: string | null) => {
    if (!gid) return '-';
    return groups.find(g => g.id === gid)?.name ?? gid;
  };

  return (
    <div className="rounded-lg border border-surface-divider dark:border-dark-divider overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface dark:bg-dark-sidebar text-text-secondary">
            <th className="px-4 py-2 text-left font-medium">用户名</th>
            <th className="px-4 py-2 text-left font-medium">显示名</th>
            <th className="px-4 py-2 text-left font-medium">角色</th>
            <th className="px-4 py-2 text-left font-medium">分组</th>
            <th className="px-4 py-2 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {users.map(u => (
            <tr key={u.id} className="border-t border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-card">
              <td className="px-4 py-2 text-text-primary dark:text-text-dark-primary">{u.username}</td>
              <td className="px-4 py-2 text-text-primary dark:text-text-dark-primary">{u.display_name}</td>
              <td className="px-4 py-2">
                <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                  u.system_role === 'admin'
                    ? 'bg-primary/10 text-primary'
                    : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                }`}>
                  {u.system_role === 'admin' ? '管理员' : '用户'}
                </span>
              </td>
              <td className="px-4 py-2 text-text-secondary">{getGroupName(u.group_id)}</td>
              <td className="px-4 py-2 text-right space-x-2">
                <button
                  onClick={() => void onToggleRole(u)}
                  className="text-xs text-text-secondary hover:text-primary transition-colors"
                >
                  {u.system_role === 'admin' ? '降为用户' : '升为管理员'}
                </button>
                <button
                  onClick={() => void onDelete(u.id)}
                  className="text-xs text-text-secondary hover:text-red-500 transition-colors"
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr><td colSpan={5} className="px-4 py-8 text-center text-text-secondary">暂无用户</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function GroupTable({ groups, onDelete }: {
  groups: Group[];
  onDelete: (id: string) => Promise<void>;
}) {
  return (
    <div className="rounded-lg border border-surface-divider dark:border-dark-divider overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface dark:bg-dark-sidebar text-text-secondary">
            <th className="px-4 py-2 text-left font-medium">组名</th>
            <th className="px-4 py-2 text-left font-medium">描述</th>
            <th className="px-4 py-2 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {groups.map(g => (
            <tr key={g.id} className="border-t border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-card">
              <td className="px-4 py-2 text-text-primary dark:text-text-dark-primary">{g.name}</td>
              <td className="px-4 py-2 text-text-secondary">{g.description || '-'}</td>
              <td className="px-4 py-2 text-right">
                <button
                  onClick={() => void onDelete(g.id)}
                  className="text-xs text-text-secondary hover:text-red-500 transition-colors"
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
          {groups.length === 0 && (
            <tr><td colSpan={3} className="px-4 py-8 text-center text-text-secondary">暂无用户组</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ===== 资源授权 Tab =====
type ResType = 'role' | 'skill' | 'knowledge' | 'knowhow';
const RES_LABELS: Record<ResType, string> = { role: 'AI角色', skill: 'Skill', knowledge: '知识文件', knowhow: 'Know-how规约' };

function GrantsTab({ users, groups }: { users: User[]; groups: Group[] }) {
  const [resType, setResType] = useState<ResType>('role');
  const [resources, setResources] = useState<{ id: string; name: string }[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { toast, showToast } = useToast();
  const [newGrantType, setNewGrantType] = useState<'public' | 'group' | 'user'>('public');
  const [newGrantee, setNewGrantee] = useState('');

  const loadResources = useCallback(async () => {
    setLoading(true);
    try {
      if (resType === 'role') {
        const roles: Role[] = await listRoles();
        setResources(roles.map(r => ({ id: r.id, name: r.name })));
      } else if (resType === 'skill') {
        const skills: SkillMeta[] = await listSkills();
        setResources(skills.map(s => ({ id: s.id, name: s.name })));
      } else if (resType === 'knowledge') {
        const { imports } = await listKnowledgeImports();
        setResources(imports.map(i => ({ id: i.id, name: i.file_name })));
      } else {
        const rules = await listKnowhowRules();
        setResources(rules.map(r => ({ id: r.id, name: `[${r.category}] ${r.rule_text.slice(0, 40)}` })));
      }
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, [resType]);

  useEffect(() => {
    setSelectedId(null);
    setGrants([]);
    void loadResources();
  }, [loadResources]);

  const handleSelectResource = async (id: string) => {
    setSelectedId(id);
    setLoading(true);
    try {
      const g = await listGrants(resType, id);
      setGrants(g);
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  };

  const handleAddGrant = async () => {
    if (!selectedId) return;
    setLoading(true);
    try {
      await setGrant({
        resource_type: resType,
        resource_id: selectedId,
        grant_type: newGrantType,
        grantee_id: newGrantType === 'public' ? undefined : newGrantee || undefined,
      });
      const g = await listGrants(resType, selectedId);
      setGrants(g);
      setNewGrantee('');
      showToast('授权成功');
    } catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const handleRemoveGrant = async (grantId: string) => {
    setLoading(true);
    try {
      await removeGrant(grantId);
      if (selectedId) {
        const g = await listGrants(resType, selectedId);
        setGrants(g);
      }
      showToast('授权已撤销');
    } catch (e) { setError((e as Error).message); showToast((e as Error).message, false); }
    finally { setLoading(false); }
  };

  const formatGrantee = (grant: AccessGrant) => {
    if (grant.grant_type === 'public') return '所有人（公开）';
    if (grant.grant_type === 'group') {
      const g = groups.find(g => g.id === grant.grantee_id);
      return `组: ${g ? g.name : grant.grantee_id}`;
    }
    const u = users.find(u => u.id === grant.grantee_id);
    return `用户: ${u ? u.display_name : grant.grantee_id}`;
  };

  const selectCls = 'rounded border border-surface-divider bg-white px-2 py-1.5 text-sm dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-primary';

  return (
    <div className="space-y-4 relative">
      {/* Toast 提示 */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 rounded-md px-4 py-2 text-sm text-white shadow-lg transition-all ${
          toast.ok ? 'bg-green-500' : 'bg-red-500'
        }`}>
          {toast.msg}
        </div>
      )}

      {/* 加载遮罩 */}
      {loading && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-white/50 dark:bg-dark-card/50">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}

      {error && (
        <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 underline">关闭</button>
        </div>
      )}

      {/* 资源类型选择器 */}
      <div className="flex gap-2">
        {(['role', 'skill', 'knowledge', 'knowhow'] as ResType[]).map(t => (
          <button
            key={t}
            onClick={() => setResType(t)}
            className={`rounded px-3 py-1.5 text-sm transition-colors ${
              resType === t
                ? 'bg-primary text-white'
                : 'border border-surface-divider dark:border-dark-divider text-text-secondary hover:text-text-primary'
            }`}
          >
            {RES_LABELS[t]}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* 左：资源列表 */}
        <div className="rounded-lg border border-surface-divider dark:border-dark-divider overflow-hidden">
          <div className="bg-surface dark:bg-dark-sidebar px-4 py-2 text-xs font-medium text-text-secondary">
            选择{RES_LABELS[resType]}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {resources.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-text-secondary">暂无资源</div>
            )}
            {resources.map(r => (
              <button
                key={r.id}
                onClick={() => void handleSelectResource(r.id)}
                className={`w-full text-left px-4 py-2.5 text-sm border-t border-surface-divider dark:border-dark-divider transition-colors ${
                  selectedId === r.id
                    ? 'bg-primary/10 text-primary'
                    : 'bg-white dark:bg-dark-card text-text-primary dark:text-text-dark-primary hover:bg-surface dark:hover:bg-dark-sidebar'
                }`}
              >
                {r.name}
              </button>
            ))}
          </div>
        </div>

        {/* 右：授权管理 */}
        <div className="rounded-lg border border-surface-divider dark:border-dark-divider overflow-hidden">
          <div className="bg-surface dark:bg-dark-sidebar px-4 py-2 text-xs font-medium text-text-secondary">
            {selectedId ? '授权管理' : '请先选择资源'}
          </div>

          {!selectedId && (
            <div className="px-4 py-8 text-center text-sm text-text-secondary">在左侧选择一个资源后，可在此设置其访问权限</div>
          )}

          {selectedId && (
            <div className="p-3 space-y-3">
              {/* 添加授权表单 */}
              <div className="flex gap-2 flex-wrap items-center">
                <select
                  className={selectCls}
                  value={newGrantType}
                  onChange={e => { setNewGrantType(e.target.value as 'public' | 'group' | 'user'); setNewGrantee(''); }}
                >
                  <option value="public">公开（所有人）</option>
                  <option value="group">指定用户组</option>
                  <option value="user">指定用户</option>
                </select>

                {newGrantType === 'group' && (
                  <select className={selectCls} value={newGrantee} onChange={e => setNewGrantee(e.target.value)}>
                    <option value="">选择用户组</option>
                    {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                )}

                {newGrantType === 'user' && (
                  <select className={selectCls} value={newGrantee} onChange={e => setNewGrantee(e.target.value)}>
                    <option value="">选择用户</option>
                    {users.map(u => <option key={u.id} value={u.id}>{u.display_name}</option>)}
                  </select>
                )}

                <button
                  onClick={() => void handleAddGrant()}
                  disabled={newGrantType !== 'public' && !newGrantee}
                  className="win-button-primary px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  授权
                </button>
              </div>

              {/* 已有授权列表 */}
              <div className="space-y-1 max-h-56 overflow-y-auto">
                {grants.length === 0 && (
                  <p className="py-4 text-center text-sm text-text-secondary">暂无授权，默认仅创建者可见</p>
                )}
                {grants.map(grant => (
                  <div key={grant.id} className="flex items-center justify-between rounded bg-surface dark:bg-dark-sidebar px-3 py-1.5 text-sm">
                    <span className="text-text-primary dark:text-text-dark-primary">{formatGrantee(grant)}</span>
                    <button
                      onClick={() => void handleRemoveGrant(grant.id)}
                      className="text-xs text-text-secondary hover:text-red-500 transition-colors ml-4 flex-shrink-0"
                    >
                      撤销
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
