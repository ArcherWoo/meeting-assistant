/**
 * 管理员面板 - 用户、用户组和资源授权管理
 */
import { useCallback, useEffect, useState } from 'react';
import type { AccessGrant, Group, Role, SkillMeta, User } from '@/types';
import { hasInvalidatedResource, subscribeAppDataInvalidation } from '@/utils/appInvalidation';
import { useConfirm } from '@/hooks/useConfirm';
import {
  createGroup,
  deleteGroup,
  deleteUser,
  listGrants,
  listGroups,
  listKnowhowRules,
  listKnowledgeImports,
  listRoles,
  listSkills,
  listUsers,
  registerUser,
  removeGrant,
  setGrant,
  updateGroup,
  updateUser,
} from '@/services/api';

type Tab = 'users' | 'groups' | 'grants';
type Toast = { msg: string; ok: boolean };
type CreateUserFormState = {
  username: string;
  display_name: string;
  password: string;
  system_role: 'user' | 'admin';
  group_id: string;
};
type EditUserFormState = {
  display_name: string;
  group_id: string;
  password: string;
};
type GroupFormState = {
  name: string;
  description: string;
};
type ResType = 'role' | 'skill' | 'knowledge' | 'knowhow';

const DEFAULT_ADMIN_USERNAME = 'admin';
const RES_LABELS: Record<ResType, string> = {
  role: 'AI角色',
  skill: 'Skill',
  knowledge: '知识文件',
  knowhow: 'Know-how规则',
};
const EMPTY_NEW_USER: CreateUserFormState = {
  username: '',
  display_name: '',
  password: '',
  system_role: 'user',
  group_id: '',
};
const EMPTY_EDIT_USER: EditUserFormState = {
  display_name: '',
  group_id: '',
  password: '',
};
const EMPTY_GROUP_FORM: GroupFormState = {
  name: '',
  description: '',
};

function useToast() {
  const [toast, setToastState] = useState<Toast | null>(null);

  const showToast = (msg: string, ok = true) => {
    setToastState({ msg, ok });
    setTimeout(() => setToastState(null), 3000);
  };

  const dismissToast = () => setToastState(null);

  return { toast, showToast, dismissToast };
}

export default function AdminPanel() {
  const confirm = useConfirm();
  const [tab, setTab] = useState<Tab>('users');
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { toast, showToast, dismissToast } = useToast();

  const [showAddUser, setShowAddUser] = useState(false);
  const [newUser, setNewUser] = useState<CreateUserFormState>(EMPTY_NEW_USER);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editUserForm, setEditUserForm] = useState<EditUserFormState>(EMPTY_EDIT_USER);

  const [showAddGroup, setShowAddGroup] = useState(false);
  const [newGroup, setNewGroup] = useState<GroupFormState>(EMPTY_GROUP_FORM);
  const [editingGroup, setEditingGroup] = useState<Group | null>(null);
  const [editGroupForm, setEditGroupForm] = useState<GroupFormState>(EMPTY_GROUP_FORM);

  const refresh = useCallback(async () => {
    try {
      const [fetchedUsers, fetchedGroups] = await Promise.all([listUsers(), listGroups()]);
      setUsers(fetchedUsers);
      setGroups(fetchedGroups);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => subscribeAppDataInvalidation((resources) => {
    if (hasInvalidatedResource(resources, ['users', 'groups'])) {
      void refresh();
    }
  }), [refresh]);

  const inputCls =
    'w-full rounded-md border border-surface-divider bg-white px-3 py-2 text-sm ' +
    'focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 ' +
    'dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-primary';

  const handleAddUser = async () => {
    const username = newUser.username.trim();
    const displayName = newUser.display_name.trim();
    const password = newUser.password.trim();
    if (!username || !displayName || !password) {
      showToast('用户名、显示名和密码不能为空', false);
      return;
    }

    setLoading(true);
    try {
      await registerUser({
        ...newUser,
        username,
        display_name: displayName,
        password,
        group_id: newUser.group_id || undefined,
      });
      setShowAddUser(false);
      setNewUser(EMPTY_NEW_USER);
      await refresh();
      showToast('用户创建成功');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleStartEditUser = (user: User) => {
    setShowAddUser(false);
    setEditingUser(user);
    setEditUserForm({
      display_name: user.display_name,
      group_id: user.group_id ?? '',
      password: '',
    });
  };

  const handleCancelEditUser = () => {
    setEditingUser(null);
    setEditUserForm(EMPTY_EDIT_USER);
  };

  const handleSaveUser = async () => {
    if (!editingUser) return;

    const displayName = editUserForm.display_name.trim();
    const password = editUserForm.password.trim();
    if (!displayName) {
      showToast('显示名不能为空', false);
      return;
    }

    setLoading(true);
    try {
      const payload: Record<string, unknown> = {
        display_name: displayName,
        group_id: editUserForm.group_id,
      };
      if (password) {
        payload.password = password;
      }
      await updateUser(editingUser.id, payload);
      await refresh();
      handleCancelEditUser();
      showToast('用户修改成功');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (id: string) => {
    const targetUser = users.find((user) => user.id === id);
    if (targetUser?.username === DEFAULT_ADMIN_USERNAME) {
      showToast('?? admin ??????', false);
      return;
    }

    const confirmed = await confirm({
      title: `删除用户「${targetUser?.display_name || targetUser?.username || '未命名用户'}」？`,
      description: '删除后该账号将无法继续登录，操作不可恢复。',
      confirmLabel: '确认删除',
      tone: 'danger',
    });
    if (!confirmed) return;

    setLoading(true);
    try {
      await deleteUser(id);
      if (editingUser?.id === id) {
        handleCancelEditUser();
      }
      await refresh();
      showToast('?????');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleRole = async (user: User) => {
    if (user.username === DEFAULT_ADMIN_USERNAME && user.system_role === 'admin') {
      showToast('默认 admin 账号不能降级', false);
      return;
    }

    setLoading(true);
    try {
      const newRole: User['system_role'] = user.system_role === 'admin' ? 'user' : 'admin';
      await updateUser(user.id, { system_role: newRole });
      await refresh();
      showToast(newRole === 'admin' ? '已升为管理员' : '已降为普通用户');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleAddGroup = async () => {
    const name = newGroup.name.trim();
    if (!name) {
      showToast('用户组名称不能为空', false);
      return;
    }

    setLoading(true);
    try {
      await createGroup(name, newGroup.description.trim());
      setShowAddGroup(false);
      setNewGroup(EMPTY_GROUP_FORM);
      await refresh();
      showToast('用户组创建成功');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleStartEditGroup = (group: Group) => {
    setShowAddGroup(false);
    setEditingGroup(group);
    setEditGroupForm({
      name: group.name,
      description: group.description ?? '',
    });
  };

  const handleCancelEditGroup = () => {
    setEditingGroup(null);
    setEditGroupForm(EMPTY_GROUP_FORM);
  };

  const handleSaveGroup = async () => {
    if (!editingGroup) return;

    const name = editGroupForm.name.trim();
    if (!name) {
      showToast('用户组名称不能为空', false);
      return;
    }

    setLoading(true);
    try {
      await updateGroup(editingGroup.id, {
        name,
        description: editGroupForm.description.trim(),
      });
      await refresh();
      handleCancelEditGroup();
      showToast('用户组修改成功');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteGroup = async (id: string) => {
    const targetGroup = groups.find((group) => group.id === id);
    const confirmed = await confirm({
      title: `删除用户组「${targetGroup?.name || '未命名用户组'}」？`,
      description: '删除后，关联用户组授权将一并失效，请确认当前分组已不再使用。',
      confirmLabel: '确认删除',
      tone: 'danger',
    });
    if (!confirmed) return;

    setLoading(true);
    try {
      await deleteGroup(id);
      if (editingGroup?.id === id) {
        handleCancelEditGroup();
      }
      await refresh();
      showToast('??????');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex-1 overflow-y-auto p-6">
      <h1 className="mb-4 text-lg font-semibold text-text-primary dark:text-text-dark-primary">用户管理</h1>

      {toast && (
        <div
          className={`fixed right-4 top-4 z-50 max-w-sm rounded-md px-4 py-3 text-sm text-white shadow-lg transition-all ${
            toast.ok ? 'bg-green-500' : 'bg-red-500'
          }`}
        >
          <div className="flex items-start gap-3">
            <span className="min-w-0 flex-1 break-words">{toast.msg}</span>
            <button
              type="button"
              onClick={dismissToast}
              className="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded border border-white/20 text-base opacity-80 transition hover:opacity-100"
              aria-label="关闭通知"
              title="关闭通知"
            >
              ×
            </button>
          </div>
        </div>
      )}

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

      <div className="mb-4 flex w-fit gap-1 rounded-md border border-surface-divider bg-surface p-1 dark:border-dark-divider dark:bg-dark-sidebar">
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
          <button
            onClick={() => {
              setShowAddUser((value) => !value);
              if (editingUser) handleCancelEditUser();
            }}
            className="win-button-primary px-4 py-2 text-sm"
          >
            {showAddUser ? '取消' : '+ 添加用户'}
          </button>

          {showAddUser && (
            <div className="space-y-3 rounded-lg border border-surface-divider bg-white p-4 dark:border-dark-divider dark:bg-dark-card">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <input
                  className={inputCls}
                  placeholder="用户名"
                  value={newUser.username}
                  onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                />
                <input
                  className={inputCls}
                  placeholder="显示名"
                  value={newUser.display_name}
                  onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })}
                />
                <input
                  className={inputCls}
                  type="password"
                  placeholder="密码"
                  value={newUser.password}
                  onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                />
                <select
                  className={inputCls}
                  value={newUser.system_role}
                  onChange={(e) => setNewUser({ ...newUser, system_role: e.target.value as 'user' | 'admin' })}
                >
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
                <select
                  className={inputCls}
                  value={newUser.group_id}
                  onChange={(e) => setNewUser({ ...newUser, group_id: e.target.value })}
                >
                  <option value="">无分组</option>
                  {groups.map((group) => (
                    <option key={group.id} value={group.id}>{group.name}</option>
                  ))}
                </select>
              </div>
              <button
                onClick={() => void handleAddUser()}
                disabled={!newUser.username.trim() || !newUser.display_name.trim() || !newUser.password.trim()}
                className="win-button-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                创建
              </button>
            </div>
          )}

          {editingUser && (
            <div className="space-y-3 rounded-lg border border-surface-divider bg-white p-4 dark:border-dark-divider dark:bg-dark-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">修改用户</h2>
                  <p className="text-xs text-text-secondary">当前用户：{editingUser.username}</p>
                </div>
                <button onClick={handleCancelEditUser} className="text-sm text-text-secondary hover:text-text-primary">
                  取消
                </button>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <input
                  className={inputCls}
                  placeholder="显示名"
                  value={editUserForm.display_name}
                  onChange={(e) => setEditUserForm({ ...editUserForm, display_name: e.target.value })}
                />
                <select
                  className={inputCls}
                  value={editUserForm.group_id}
                  onChange={(e) => setEditUserForm({ ...editUserForm, group_id: e.target.value })}
                >
                  <option value="">无分组</option>
                  {groups.map((group) => (
                    <option key={group.id} value={group.id}>{group.name}</option>
                  ))}
                </select>
                <input
                  className={inputCls}
                  type="password"
                  placeholder="新密码（留空则不修改）"
                  value={editUserForm.password}
                  onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })}
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => void handleSaveUser()}
                  disabled={!editUserForm.display_name.trim()}
                  className="win-button-primary px-4 py-2 text-sm disabled:opacity-50"
                >
                  保存
                </button>
                <button
                  onClick={handleCancelEditUser}
                  className="rounded-md border border-surface-divider px-4 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary dark:border-dark-divider"
                >
                  取消
                </button>
              </div>
            </div>
          )}

          <UserTable
            users={users}
            groups={groups}
            onEdit={handleStartEditUser}
            onDelete={handleDeleteUser}
            onToggleRole={handleToggleRole}
          />
        </div>
      )}

      {tab === 'groups' && (
        <div className="space-y-3">
          <button
            onClick={() => {
              setShowAddGroup((value) => !value);
              if (editingGroup) handleCancelEditGroup();
            }}
            className="win-button-primary px-4 py-2 text-sm"
          >
            {showAddGroup ? '取消' : '+ 添加用户组'}
          </button>

          {showAddGroup && (
            <div className="space-y-3 rounded-lg border border-surface-divider bg-white p-4 dark:border-dark-divider dark:bg-dark-card">
              <input
                className={inputCls}
                placeholder="组名"
                value={newGroup.name}
                onChange={(e) => setNewGroup({ ...newGroup, name: e.target.value })}
              />
              <input
                className={inputCls}
                placeholder="描述（可选）"
                value={newGroup.description}
                onChange={(e) => setNewGroup({ ...newGroup, description: e.target.value })}
              />
              <button
                onClick={() => void handleAddGroup()}
                disabled={!newGroup.name.trim()}
                className="win-button-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                创建
              </button>
            </div>
          )}

          {editingGroup && (
            <div className="space-y-3 rounded-lg border border-surface-divider bg-white p-4 dark:border-dark-divider dark:bg-dark-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">修改用户组</h2>
                  <p className="text-xs text-text-secondary">当前用户组：{editingGroup.name}</p>
                </div>
                <button onClick={handleCancelEditGroup} className="text-sm text-text-secondary hover:text-text-primary">
                  取消
                </button>
              </div>
              <input
                className={inputCls}
                placeholder="组名"
                value={editGroupForm.name}
                onChange={(e) => setEditGroupForm({ ...editGroupForm, name: e.target.value })}
              />
              <input
                className={inputCls}
                placeholder="描述（可选）"
                value={editGroupForm.description}
                onChange={(e) => setEditGroupForm({ ...editGroupForm, description: e.target.value })}
              />
              <div className="flex gap-2">
                <button
                  onClick={() => void handleSaveGroup()}
                  disabled={!editGroupForm.name.trim()}
                  className="win-button-primary px-4 py-2 text-sm disabled:opacity-50"
                >
                  保存
                </button>
                <button
                  onClick={handleCancelEditGroup}
                  className="rounded-md border border-surface-divider px-4 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary dark:border-dark-divider"
                >
                  取消
                </button>
              </div>
            </div>
          )}

          <GroupTable groups={groups} onEdit={handleStartEditGroup} onDelete={handleDeleteGroup} />
        </div>
      )}

      {tab === 'grants' && (
        <GrantsTab users={users} groups={groups} />
      )}
    </div>
  );
}

function UserTable({
  users,
  groups,
  onEdit,
  onDelete,
  onToggleRole,
}: {
  users: User[];
  groups: Group[];
  onEdit: (user: User) => void;
  onDelete: (id: string) => Promise<void>;
  onToggleRole: (user: User) => Promise<void>;
}) {
  const getGroupName = (groupId: string | null) => {
    if (!groupId) return '-';
    return groups.find((group) => group.id === groupId)?.name ?? groupId;
  };

  return (
    <div className="overflow-hidden rounded-lg border border-surface-divider dark:border-dark-divider">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface text-text-secondary dark:bg-dark-sidebar">
            <th className="px-4 py-2 text-left font-medium">用户名</th>
            <th className="px-4 py-2 text-left font-medium">显示名</th>
            <th className="px-4 py-2 text-left font-medium">角色</th>
            <th className="px-4 py-2 text-left font-medium">分组</th>
            <th className="px-4 py-2 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => {
            const isDefaultAdmin = user.username === DEFAULT_ADMIN_USERNAME && user.system_role === 'admin';
            return (
              <tr
                key={user.id}
                className="border-t border-surface-divider bg-white dark:border-dark-divider dark:bg-dark-card"
              >
                <td className="px-4 py-2 text-text-primary dark:text-text-dark-primary">{user.username}</td>
                <td className="px-4 py-2 text-text-primary dark:text-text-dark-primary">{user.display_name}</td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                      user.system_role === 'admin'
                        ? 'bg-primary/10 text-primary'
                        : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                    }`}
                  >
                    {user.system_role === 'admin' ? '管理员' : '用户'}
                  </span>
                </td>
                <td className="px-4 py-2 text-text-secondary">{getGroupName(user.group_id)}</td>
                <td className="px-4 py-2 text-right">
                  <div className="flex flex-wrap justify-end gap-3">
                    <button
                      onClick={() => onEdit(user)}
                      className="text-xs text-text-secondary transition-colors hover:text-primary"
                    >
                      修改
                    </button>
                    {!isDefaultAdmin && (
                      <button
                        onClick={() => void onToggleRole(user)}
                        className="text-xs text-text-secondary transition-colors hover:text-primary"
                      >
                        {user.system_role === 'admin' ? '降为用户' : '升为管理员'}
                      </button>
                    )}
                    {isDefaultAdmin && (
                      <span className="text-xs text-text-secondary">默认 admin 不可降级或删除</span>
                    )}
                    {!isDefaultAdmin && (
                      <button
                        onClick={() => void onDelete(user.id)}
                        className="text-xs text-text-secondary transition-colors hover:text-red-500"
                      >
                        删除
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
          {users.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-text-secondary">暂无用户</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function GroupTable({
  groups,
  onEdit,
  onDelete,
}: {
  groups: Group[];
  onEdit: (group: Group) => void;
  onDelete: (id: string) => Promise<void>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-surface-divider dark:border-dark-divider">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface text-text-secondary dark:bg-dark-sidebar">
            <th className="px-4 py-2 text-left font-medium">组名</th>
            <th className="px-4 py-2 text-left font-medium">描述</th>
            <th className="px-4 py-2 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr
              key={group.id}
              className="border-t border-surface-divider bg-white dark:border-dark-divider dark:bg-dark-card"
            >
              <td className="px-4 py-2 text-text-primary dark:text-text-dark-primary">{group.name}</td>
              <td className="px-4 py-2 text-text-secondary">{group.description || '-'}</td>
              <td className="px-4 py-2 text-right">
                <div className="flex flex-wrap justify-end gap-3">
                  <button
                    onClick={() => onEdit(group)}
                    className="text-xs text-text-secondary transition-colors hover:text-primary"
                  >
                    修改
                  </button>
                  <button
                    onClick={() => void onDelete(group.id)}
                    className="text-xs text-text-secondary transition-colors hover:text-red-500"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {groups.length === 0 && (
            <tr>
              <td colSpan={3} className="px-4 py-8 text-center text-text-secondary">暂无用户组</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function GrantsTab({ users, groups }: { users: User[]; groups: Group[] }) {
  const [resType, setResType] = useState<ResType>('role');
  const [resources, setResources] = useState<{ id: string; name: string }[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { toast, showToast, dismissToast } = useToast();
  const [newGrantType, setNewGrantType] = useState<'public' | 'group' | 'user'>('public');
  const [newGrantee, setNewGrantee] = useState('');

  const loadResources = useCallback(async () => {
    setLoading(true);
    try {
      if (resType === 'role') {
        const roles: Role[] = await listRoles();
        setResources(roles.map((role) => ({ id: role.id, name: role.name })));
      } else if (resType === 'skill') {
        const skills: SkillMeta[] = await listSkills();
        setResources(skills.map((skill) => ({ id: skill.id, name: skill.name })));
      } else if (resType === 'knowledge') {
        const { imports } = await listKnowledgeImports();
        setResources(imports.map((item) => ({ id: item.id, name: item.file_name })));
      } else {
        const rules = await listKnowhowRules();
        setResources(
          rules.map((rule) => ({
            id: rule.id,
            name: `[${rule.category}] ${rule.rule_text.slice(0, 40)}`,
          })),
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
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
      const fetchedGrants = await listGrants(resType, id);
      setGrants(fetchedGrants);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => subscribeAppDataInvalidation((resources) => {
    if (hasInvalidatedResource(resources, ['roles', 'skills', 'knowledge', 'knowhow'])) {
      void loadResources();
      if (selectedId) {
        void handleSelectResource(selectedId);
      }
    }
  }), [handleSelectResource, loadResources, selectedId]);

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
      const fetchedGrants = await listGrants(resType, selectedId);
      setGrants(fetchedGrants);
      setNewGrantee('');
      showToast('授权成功');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveGrant = async (grantId: string) => {
    setLoading(true);
    try {
      await removeGrant(grantId);
      if (selectedId) {
        const fetchedGrants = await listGrants(resType, selectedId);
        setGrants(fetchedGrants);
      }
      showToast('授权已撤销');
    } catch (e) {
      setError((e as Error).message);
      showToast((e as Error).message, false);
    } finally {
      setLoading(false);
    }
  };

  const formatGrantee = (grant: AccessGrant) => {
    if (grant.grant_type === 'public') return '所有人（公开）';
    if (grant.grant_type === 'group') {
      const group = groups.find((item) => item.id === grant.grantee_id);
      return `组: ${group ? group.name : grant.grantee_id}`;
    }
    const user = users.find((item) => item.id === grant.grantee_id);
    return `用户: ${user ? user.display_name : grant.grantee_id}`;
  };

  const selectCls =
    'rounded border border-surface-divider bg-white px-2 py-1.5 text-sm ' +
    'dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-primary';

  return (
    <div className="relative space-y-4">
      {toast && (
        <div
          className={`fixed right-4 top-4 z-50 max-w-sm rounded-md px-4 py-3 text-sm text-white shadow-lg transition-all ${
            toast.ok ? 'bg-green-500' : 'bg-red-500'
          }`}
        >
          <div className="flex items-start gap-3">
            <span className="min-w-0 flex-1 break-words">{toast.msg}</span>
            <button
              type="button"
              onClick={dismissToast}
              className="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded border border-white/20 text-base opacity-80 transition hover:opacity-100"
              aria-label="关闭通知"
              title="关闭通知"
            >
              ×
            </button>
          </div>
        </div>
      )}

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

      <div className="flex gap-2">
        {(['role', 'skill', 'knowledge', 'knowhow'] as ResType[]).map((type) => (
          <button
            key={type}
            onClick={() => setResType(type)}
            className={`rounded px-3 py-1.5 text-sm transition-colors ${
              resType === type
                ? 'bg-primary text-white'
                : 'border border-surface-divider text-text-secondary hover:text-text-primary dark:border-dark-divider'
            }`}
          >
            {RES_LABELS[type]}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="overflow-hidden rounded-lg border border-surface-divider dark:border-dark-divider">
          <div className="bg-surface px-4 py-2 text-xs font-medium text-text-secondary dark:bg-dark-sidebar">
            选择{RES_LABELS[resType]}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {resources.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-text-secondary">暂无资源</div>
            )}
            {resources.map((resource) => (
              <button
                key={resource.id}
                onClick={() => void handleSelectResource(resource.id)}
                className={`w-full border-t border-surface-divider px-4 py-2.5 text-left text-sm transition-colors dark:border-dark-divider ${
                  selectedId === resource.id
                    ? 'bg-primary/10 text-primary'
                    : 'bg-white text-text-primary hover:bg-surface dark:bg-dark-card dark:text-text-dark-primary dark:hover:bg-dark-sidebar'
                }`}
              >
                {resource.name}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-surface-divider dark:border-dark-divider">
          <div className="bg-surface px-4 py-2 text-xs font-medium text-text-secondary dark:bg-dark-sidebar">
            {selectedId ? '授权管理' : '请先选择资源'}
          </div>

          {!selectedId && (
            <div className="px-4 py-8 text-center text-sm text-text-secondary">
              在左侧选择一个资源后，可在此设置其访问权限
            </div>
          )}

          {selectedId && (
            <div className="space-y-3 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className={selectCls}
                  value={newGrantType}
                  onChange={(e) => {
                    setNewGrantType(e.target.value as 'public' | 'group' | 'user');
                    setNewGrantee('');
                  }}
                >
                  <option value="public">公开（所有人）</option>
                  <option value="group">指定用户组</option>
                  <option value="user">指定用户</option>
                </select>

                {newGrantType === 'group' && (
                  <select className={selectCls} value={newGrantee} onChange={(e) => setNewGrantee(e.target.value)}>
                    <option value="">选择用户组</option>
                    {groups.map((group) => (
                      <option key={group.id} value={group.id}>{group.name}</option>
                    ))}
                  </select>
                )}

                {newGrantType === 'user' && (
                  <select className={selectCls} value={newGrantee} onChange={(e) => setNewGrantee(e.target.value)}>
                    <option value="">选择用户</option>
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>{user.display_name}</option>
                    ))}
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

              <div className="max-h-56 space-y-1 overflow-y-auto">
                {grants.length === 0 && (
                  <p className="py-4 text-center text-sm text-text-secondary">暂无授权，默认仅创建者可见</p>
                )}
                {grants.map((grant) => (
                  <div
                    key={grant.id}
                    className="flex items-center justify-between rounded bg-surface px-3 py-1.5 text-sm dark:bg-dark-sidebar"
                  >
                    <span className="text-text-primary dark:text-text-dark-primary">{formatGrantee(grant)}</span>
                    <button
                      onClick={() => void handleRemoveGrant(grant.id)}
                      className="ml-4 flex-shrink-0 text-xs text-text-secondary transition-colors hover:text-red-500"
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
