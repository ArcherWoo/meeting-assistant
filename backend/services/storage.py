"""
SQLite 存储服务 - 统一数据库连接与 Schema 管理
遵循 PRD §13.1 数据库设计，所有表均在 ~/.meeting-assistant/data/main.db 中
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import aiosqlite
from services.runtime_paths import DB_PATH

# ===== Schema 定义（PRD §13.1）=====
_SCHEMA_SQL = """
-- 工作区表
CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon        TEXT DEFAULT '📁',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_archived INTEGER DEFAULT 0
);

-- 对话表
CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL,
    title         TEXT DEFAULT '新对话',
    surface       TEXT DEFAULT 'chat',
    role_id       TEXT,
    is_pinned     INTEGER DEFAULT 0,
    is_title_customized INTEGER DEFAULT 0,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_conv_workspace ON conversations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at DESC);

-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    model           TEXT,
    token_input     INTEGER DEFAULT 0,
    token_output    INTEGER DEFAULT 0,
    duration_ms     INTEGER DEFAULT 0,
    metadata        TEXT DEFAULT '{}',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at);

-- 附件表
CREATE TABLE IF NOT EXISTS attachments (
    id          TEXT PRIMARY KEY,
    message_id  TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    file_size   INTEGER NOT NULL,
    file_type   TEXT NOT NULL,
    parsed      INTEGER DEFAULT 0,
    parse_result TEXT DEFAULT '{}',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- 采购记录表（PPT 结构化提取）
CREATE TABLE IF NOT EXISTS procurement_records (
    id              TEXT PRIMARY KEY,
    source_file     TEXT NOT NULL,
    source_file_id  TEXT,
    category        TEXT NOT NULL,
    item_name       TEXT NOT NULL,
    supplier        TEXT,
    unit_price      REAL,
    quantity        INTEGER,
    total_price     REAL,
    currency        TEXT DEFAULT 'CNY',
    procurement_date TEXT,
    contract_terms  TEXT DEFAULT '{}',
    raw_text        TEXT,
    extracted_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    confidence      REAL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_proc_category ON procurement_records(category);
CREATE INDEX IF NOT EXISTS idx_proc_supplier ON procurement_records(supplier);
CREATE INDEX IF NOT EXISTS idx_proc_date ON procurement_records(procurement_date);
CREATE INDEX IF NOT EXISTS idx_proc_item ON procurement_records(item_name);

-- Skill 使用记录表
CREATE TABLE IF NOT EXISTS skill_usage_logs (
    id              TEXT PRIMARY KEY,
    skill_id        TEXT NOT NULL,
    conversation_id TEXT,
    input_summary   TEXT,
    output_summary  TEXT,
    success         INTEGER DEFAULT 1,
    duration_ms     INTEGER DEFAULT 0,
    user_rating     INTEGER,
    user_feedback   TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_skill_usage ON skill_usage_logs(skill_id);

-- Know-how 规则表
CREATE TABLE IF NOT EXISTS knowhow_rules (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    rule_text   TEXT NOT NULL,
    weight      INTEGER DEFAULT 2,
    hit_count   INTEGER DEFAULT 0,
    confidence  REAL DEFAULT 0.5,
    source      TEXT DEFAULT 'user',
    is_active   INTEGER DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_knowhow_category ON knowhow_rules(category);

-- 用户设置表
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- PPT 导入记录表
CREATE TABLE IF NOT EXISTS ppt_imports (
    id                   TEXT PRIMARY KEY,
    file_name            TEXT NOT NULL,
    file_hash            TEXT UNIQUE NOT NULL,
    file_size            INTEGER,
    slide_count          INTEGER,
    import_status        TEXT DEFAULT 'pending',
    extracted_items_count INTEGER DEFAULT 0,
    imported_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 角色表
CREATE TABLE IF NOT EXISTS roles (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    icon          TEXT DEFAULT '💬',
    description   TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    agent_prompt  TEXT DEFAULT '',
    capabilities  TEXT DEFAULT '[]',
    chat_capabilities TEXT DEFAULT '[]',
    agent_preflight TEXT DEFAULT '[]',
    allowed_surfaces TEXT DEFAULT '["chat"]',
    agent_allowed_tools TEXT DEFAULT '[]',
    is_builtin    INTEGER DEFAULT 0,
    sort_order    INTEGER DEFAULT 0,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_roles_sort ON roles(sort_order, created_at);

-- 通用知识片段表（无 embedding 时也可检索）
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          TEXT PRIMARY KEY,
    import_id   TEXT NOT NULL,
    source_file TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    slide_index INTEGER DEFAULT 0,
    chunk_type  TEXT DEFAULT 'text',
    chunk_index INTEGER DEFAULT 0,
    char_start  INTEGER,
    char_end    INTEGER,
    content     TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (import_id) REFERENCES ppt_imports(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_import ON knowledge_chunks(import_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source ON knowledge_chunks(source_file);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_type ON knowledge_chunks(file_type);

-- Agent 执行记录
CREATE TABLE IF NOT EXISTS agent_runs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT,
    role_id         TEXT NOT NULL,
    surface         TEXT DEFAULT 'agent',
    continue_from_run_id TEXT,
    continue_mode   TEXT DEFAULT '',
    skill_id        TEXT,
    skill_name      TEXT,
    query           TEXT NOT NULL,
    params          TEXT DEFAULT '{}',
    status          TEXT DEFAULT 'pending',
    model           TEXT DEFAULT '',
    llm_profile_id  TEXT,
    message_history TEXT DEFAULT '[]',
    final_result    TEXT DEFAULT '{}',
    error           TEXT DEFAULT '',
    started_at      DATETIME,
    completed_at    DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_role ON agent_runs(role_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_updated ON agent_runs(updated_at DESC);

-- Agent 执行步骤
CREATE TABLE IF NOT EXISTS agent_run_steps (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    step_index    INTEGER NOT NULL,
    step_key      TEXT NOT NULL,
    description   TEXT NOT NULL,
    status        TEXT DEFAULT 'pending',
    result        TEXT DEFAULT '',
    error         TEXT DEFAULT '',
    tool_name     TEXT DEFAULT '',
    metadata      TEXT DEFAULT '{}',
    started_at    DATETIME,
    completed_at  DATETIME,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
    UNIQUE(run_id, step_index)
);
CREATE INDEX IF NOT EXISTS idx_agent_run_steps_run ON agent_run_steps(run_id, step_index);
"""


def gen_id() -> str:
    """生成 UUID 字符串"""
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """返回带 UTC 时区信息的 ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


class StorageService:
    """SQLite 数据库服务 - 提供连接管理与 CRUD 操作"""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        self._db: Optional[aiosqlite.Connection] = None
        self._conversation_columns: set[str] = set()

    async def initialize(self) -> None:
        """初始化数据库：创建目录、连接、执行 Schema"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA_SQL)
        await self._run_migrations()
        self._conversation_columns = await self._table_columns("conversations")
        await self._db.commit()
        # 确保默认工作区存在
        await self._ensure_default_workspace()
        # 确保默认角色存在
        await self._ensure_default_roles()

    async def close(self) -> None:
        """关闭数据库连接"""
        if self._db:
            await self._db.close()
            self._db = None
            self._conversation_columns = set()

    @property
    def db(self) -> aiosqlite.Connection:
        """获取数据库连接（需先调用 initialize）"""
        if not self._db:
            raise RuntimeError("StorageService 未初始化，请先调用 initialize()")
        return self._db

    async def _table_columns(self, table_name: str) -> set[str]:
        cursor = await self.db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        return {str(row["name"]) for row in rows}

    async def _run_migrations(self) -> None:
        """补齐历史数据库缺失字段，将旧 conversations 表升级为角色会话模型。"""
        conversation_columns = await self._table_columns("conversations")

        if "role_id" not in conversation_columns:
            await self.db.execute("ALTER TABLE conversations ADD COLUMN role_id TEXT")
        if "surface" not in conversation_columns:
            await self.db.execute("ALTER TABLE conversations ADD COLUMN surface TEXT DEFAULT 'chat'")
        if "is_title_customized" not in conversation_columns:
            await self.db.execute(
                "ALTER TABLE conversations ADD COLUMN is_title_customized INTEGER DEFAULT 0"
            )

        role_columns = await self._table_columns("roles")
        if "agent_prompt" not in role_columns:
            await self.db.execute("ALTER TABLE roles ADD COLUMN agent_prompt TEXT DEFAULT ''")
        if "chat_capabilities" not in role_columns:
            await self.db.execute("ALTER TABLE roles ADD COLUMN chat_capabilities TEXT DEFAULT '[]'")
        if "agent_preflight" not in role_columns:
            await self.db.execute("ALTER TABLE roles ADD COLUMN agent_preflight TEXT DEFAULT '[]'")
        if "allowed_surfaces" not in role_columns:
            await self.db.execute("ALTER TABLE roles ADD COLUMN allowed_surfaces TEXT DEFAULT '[\"chat\"]'")
        if "agent_allowed_tools" not in role_columns:
            await self.db.execute("ALTER TABLE roles ADD COLUMN agent_allowed_tools TEXT DEFAULT '[]'")

        if "mode" in conversation_columns:
            await self.db.execute(
                "UPDATE conversations SET role_id = COALESCE(NULLIF(role_id, ''), mode, 'copilot') "
                "WHERE role_id IS NULL OR TRIM(role_id) = ''"
            )
        await self.db.execute(
            "UPDATE conversations SET surface='agent' WHERE role_id IN ('agent', 'executor')"
        )
        await self.db.execute(
            "UPDATE conversations SET surface='chat' WHERE surface IS NULL OR TRIM(surface)=''"
        )
        await self.db.execute(
            "UPDATE conversations SET role_id='executor' WHERE role_id='agent'"
        )
        if "mode" in conversation_columns:
            await self.db.execute(
                "UPDATE conversations SET mode='executor' WHERE mode='agent'"
            )
        await self.db.execute(
            "UPDATE conversations SET role_id = COALESCE(NULLIF(role_id, ''), 'copilot') "
            "WHERE role_id IS NULL OR TRIM(role_id) = ''"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_role ON conversations(role_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_surface ON conversations(surface)"
        )
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS agent_runs ("
            "id TEXT PRIMARY KEY, "
            "conversation_id TEXT, "
            "role_id TEXT NOT NULL, "
            "surface TEXT DEFAULT 'agent', "
            "continue_from_run_id TEXT, "
            "continue_mode TEXT DEFAULT '', "
            "skill_id TEXT, "
            "skill_name TEXT, "
            "query TEXT NOT NULL, "
            "params TEXT DEFAULT '{}', "
            "status TEXT DEFAULT 'pending', "
            "model TEXT DEFAULT '', "
            "llm_profile_id TEXT, "
            "message_history TEXT DEFAULT '[]', "
            "final_result TEXT DEFAULT '{}', "
            "error TEXT DEFAULT '', "
            "started_at DATETIME, "
            "completed_at DATETIME, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs(conversation_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_role ON agent_runs(role_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_updated ON agent_runs(updated_at DESC)"
        )
        agent_run_columns = await self._table_columns("agent_runs")
        if "continue_from_run_id" not in agent_run_columns:
            await self.db.execute(
                "ALTER TABLE agent_runs ADD COLUMN continue_from_run_id TEXT"
            )
        if "continue_mode" not in agent_run_columns:
            await self.db.execute(
                "ALTER TABLE agent_runs ADD COLUMN continue_mode TEXT DEFAULT ''"
            )
        if "message_history" not in agent_run_columns:
            await self.db.execute(
                "ALTER TABLE agent_runs ADD COLUMN message_history TEXT DEFAULT '[]'"
            )
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS agent_run_steps ("
            "id TEXT PRIMARY KEY, "
            "run_id TEXT NOT NULL, "
            "step_index INTEGER NOT NULL, "
            "step_key TEXT NOT NULL, "
            "description TEXT NOT NULL, "
            "status TEXT DEFAULT 'pending', "
            "result TEXT DEFAULT '', "
            "error TEXT DEFAULT '', "
            "tool_name TEXT DEFAULT '', "
            "metadata TEXT DEFAULT '{}', "
            "started_at DATETIME, "
            "completed_at DATETIME, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, "
            "UNIQUE(run_id, step_index))"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_run_steps_run ON agent_run_steps(run_id, step_index)"
        )

    # ===== Workspace CRUD =====

    async def _ensure_default_workspace(self) -> None:
        """确保存在默认工作区"""
        row = await self._fetchone("SELECT id FROM workspaces LIMIT 1")
        if not row:
            await self.create_workspace("默认工作区", "系统自动创建的默认工作区", "📋")

    async def _ensure_default_roles(self) -> None:
        """Ensure seeded roles exist and migrate legacy agent -> executor."""
        import json as _json
        existing_roles = await self._fetchone("SELECT COUNT(*) AS total FROM roles")
        roles_total = int(existing_roles["total"]) if existing_roles else 0
        legacy_agent = await self._fetchone("SELECT id FROM roles WHERE id='agent'")
        executor_role = await self._fetchone("SELECT id FROM roles WHERE id='executor'")
        if legacy_agent and not executor_role:
            now = utc_now_iso()
            await self.db.execute(
                "UPDATE roles SET id='executor', name='执行助手', updated_at=? WHERE id='agent'",
                (now,),
            )
            await self.db.execute(
                "UPDATE conversations SET role_id='executor' WHERE role_id='agent'"
            )
            await self.db.execute(
                "UPDATE settings SET key='system_prompt_executor', updated_at=? WHERE key='system_prompt_agent'",
                (now,),
            )
            await self.db.commit()
        defaults = [
            {
                "id": "copilot",
                "name": "Copilot",
                "icon": "💬",
                "description": "日常问答、分析、总结",
                "system_prompt": (
                    "你是一个专业的会议助手。请根据用户的问题，提供清晰、准确、有帮助的回答。"
                    "回答时请保持简洁，优先给出结论，再补充细节。"
                ),
                "capabilities": _json.dumps(["rag"]),
                "chat_capabilities": _json.dumps(["auto_knowledge", "auto_knowhow"]),
                "agent_preflight": _json.dumps([]),
                "agent_prompt": "",
                "allowed_surfaces": _json.dumps(["chat"]),
                "agent_allowed_tools": _json.dumps([]),
                "is_builtin": 1,
                "sort_order": 0,
            },
            {
                "id": "builder",
                "name": "Skill Builder",
                "icon": "🔧",
                "description": "设计 Skill、流程和提示词",
                "system_prompt": (
                    "你是一个 Skill Builder 助手，专门帮助用户创建和优化工作流技能（Skill）。"
                    "请引导用户描述他们的工作场景和重复性任务，帮助他们将这些任务抽象为可执行的 Skill 模板。"
                    "生成的 Skill 应使用标准 Markdown 格式，包含描述、触发条件、执行步骤和输出格式。"
                ),
                "capabilities": _json.dumps(["skills"]),
                "chat_capabilities": _json.dumps(["auto_skill_suggestion"]),
                "agent_preflight": _json.dumps(["pre_match_skill"]),
                "agent_prompt": "",
                "allowed_surfaces": _json.dumps(["chat", "agent"]),
                "agent_allowed_tools": _json.dumps([
                    "get_skill_definition",
                    "extract_file_text",
                    "search_knowhow_rules",
                ]),
                "is_builtin": 1,
                "sort_order": 1,
            },
            {
                "id": "executor",
                "name": "执行助手",
                "icon": "🤖",
                "description": "分步执行、透明反馈",
                "system_prompt": (
                    "你是一个智能 Agent，能够调用各种工具和技能完成复杂任务。"
                    "请分析用户的需求，选择合适的工具，并逐步执行任务。"
                    "执行过程中保持透明，让用户了解每一步的进展。"
                ),
                "capabilities": _json.dumps(["rag", "skills"]),
                "chat_capabilities": _json.dumps([]),
                "agent_preflight": _json.dumps(["pre_match_skill", "auto_knowledge", "auto_knowhow"]),
                "agent_prompt": "",
                "allowed_surfaces": _json.dumps(["agent"]),
                "agent_allowed_tools": _json.dumps([
                    "get_skill_definition",
                    "extract_file_text",
                    "search_knowhow_rules",
                    "query_knowledge",
                ]),
                "is_builtin": 1,
                "sort_order": 2,
            },
        ]
        for role in defaults:
            existing = await self._fetchone("SELECT id FROM roles WHERE id=?", (role["id"],))
            if not existing:
                now = utc_now_iso()
                await self.db.execute(
                    "INSERT INTO roles (id, name, icon, description, system_prompt, agent_prompt, capabilities, "
                    "chat_capabilities, agent_preflight, allowed_surfaces, agent_allowed_tools, is_builtin, sort_order, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (role["id"], role["name"], role["icon"], role["description"],
                     role["system_prompt"], role["agent_prompt"], role["capabilities"],
                     role["chat_capabilities"], role["agent_preflight"], role["allowed_surfaces"], role["agent_allowed_tools"], role["is_builtin"],
                     role["sort_order"], now, now),
                )
            elif existing:
                # 若旧记录 is_builtin=1，迁移为可编辑的普通角色
                await self.db.execute(
                    "UPDATE roles SET is_builtin=1, "
                    "chat_capabilities=COALESCE(NULLIF(chat_capabilities, ''), ?), "
                    "agent_preflight=COALESCE(NULLIF(agent_preflight, ''), ?), "
                    "allowed_surfaces=COALESCE(NULLIF(allowed_surfaces, ''), ?), "
                    "agent_allowed_tools=COALESCE(NULLIF(agent_allowed_tools, ''), ?), "
                    "agent_prompt=COALESCE(agent_prompt, '') "
                    "WHERE id=?",
                    (role["chat_capabilities"], role["agent_preflight"], role["allowed_surfaces"], role["agent_allowed_tools"], role["id"]),
                )
        await self.db.commit()

    # ===== Role CRUD =====

    async def list_roles(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM roles ORDER BY sort_order ASC, created_at ASC")

    async def get_role(self, role_id: str) -> Optional[dict]:
        return await self._fetchone("SELECT * FROM roles WHERE id=?", (role_id,))

    async def create_role(
        self,
        name: str,
        icon: str = "💬",
        description: str = "",
        system_prompt: str = "",
        agent_prompt: str = "",
        capabilities: Optional[list] = None,
        chat_capabilities: Optional[list] = None,
        agent_preflight: Optional[list] = None,
        allowed_surfaces: Optional[list] = None,
        agent_allowed_tools: Optional[list] = None,
    ) -> dict:
        import json as _json
        rid = gen_id()
        now = utc_now_iso()
        caps = _json.dumps(capabilities or [])
        chat_caps = _json.dumps(chat_capabilities or [])
        preflight = _json.dumps(agent_preflight or [])
        surfaces = _json.dumps(allowed_surfaces or ["chat"])
        tools = _json.dumps(agent_allowed_tools or [])
        # 计算排序值（追加到最后）
        row = await self._fetchone("SELECT MAX(sort_order) AS max_order FROM roles")
        sort_order = (row["max_order"] or 0) + 1 if row else 1
        await self.db.execute(
            "INSERT INTO roles (id, name, icon, description, system_prompt, agent_prompt, capabilities, chat_capabilities, "
            "agent_preflight, allowed_surfaces, agent_allowed_tools, is_builtin, sort_order, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
            (
                rid,
                name,
                icon,
                description,
                system_prompt,
                agent_prompt,
                caps,
                chat_caps,
                preflight,
                surfaces,
                tools,
                sort_order,
                now,
                now,
            ),
        )
        await self.db.commit()
        return {
            "id": rid, "name": name, "icon": icon, "description": description,
            "system_prompt": system_prompt, "agent_prompt": agent_prompt,
            "capabilities": capabilities or [],
            "chat_capabilities": chat_capabilities or [],
            "agent_preflight": agent_preflight or [],
            "allowed_surfaces": allowed_surfaces or ["chat"],
            "agent_allowed_tools": agent_allowed_tools or [],
            "is_builtin": 0, "sort_order": sort_order,
            "created_at": now, "updated_at": now,
        }

    async def update_role(self, role_id: str, **kwargs) -> Optional[dict]:
        import json as _json
        allowed = {
            "name",
            "icon",
            "description",
            "system_prompt",
            "agent_prompt",
            "capabilities",
            "chat_capabilities",
            "agent_preflight",
            "allowed_surfaces",
            "agent_allowed_tools",
            "sort_order",
        }
        fields: dict = {}
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k in {"capabilities", "chat_capabilities", "agent_preflight", "allowed_surfaces", "agent_allowed_tools"} and isinstance(v, list):
                fields[k] = _json.dumps(v)
            else:
                fields[k] = v
        if not fields:
            return await self.get_role(role_id)
        fields["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(
            f"UPDATE roles SET {set_clause} WHERE id=?",
            (*fields.values(), role_id),
        )
        await self.db.commit()
        return await self.get_role(role_id)

    async def delete_role(self, role_id: str) -> bool:
        row = await self._fetchone("SELECT id FROM roles WHERE id=?", (role_id,))
        if not row:
            return False
        await self.db.execute("DELETE FROM roles WHERE id=?", (role_id,))
        await self.db.commit()
        return True

    async def create_workspace(self, name: str, description: str = "", icon: str = "📁") -> dict:
        wid = gen_id()
        now = utc_now_iso()
        await self.db.execute(
            "INSERT INTO workspaces (id, name, description, icon, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (wid, name, description, icon, now, now),
        )
        await self.db.commit()
        return {"id": wid, "name": name, "description": description, "icon": icon, "created_at": now, "updated_at": now}

    async def list_workspaces(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM workspaces WHERE is_archived=0 ORDER BY updated_at DESC")

    async def get_workspace(self, workspace_id: str) -> Optional[dict]:
        return await self._fetchone("SELECT * FROM workspaces WHERE id=?", (workspace_id,))

    async def get_default_workspace_id(self) -> str:
        row = await self._fetchone(
            "SELECT id FROM workspaces WHERE is_archived=0 ORDER BY created_at ASC LIMIT 1"
        )
        if row:
            return str(row["id"])

        workspace = await self.create_workspace("默认工作区", "系统自动创建的默认工作区", "📋")
        return str(workspace["id"])

    # ===== Conversation CRUD =====

    @staticmethod
    def _normalize_conversation_row(row: dict) -> dict:
        role_id = str(row.get("role_id") or "copilot")
        surface = str(row.get("surface") or "chat")
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "workspaceId": row["workspace_id"],
            "title": row.get("title") or "新对话",
            "surface": surface,
            "role_id": role_id,
            "roleId": role_id,
            "is_pinned": int(row.get("is_pinned") or 0),
            "isPinned": bool(row.get("is_pinned") or 0),
            "is_title_customized": int(row.get("is_title_customized") or 0),
            "isTitleCustomized": bool(row.get("is_title_customized") or 0),
            "created_at": row["created_at"],
            "createdAt": row["created_at"],
            "updated_at": row["updated_at"],
            "updatedAt": row["updated_at"],
            "last_message": row.get("last_message") or "",
            "lastMessage": row.get("last_message") or "",
        }

    async def create_conversation(
        self,
        workspace_id: str,
        title: str = "新对话",
        surface: str = "chat",
        role_id: str = "copilot",
        is_title_customized: int = 0,
    ) -> dict:
        cid = gen_id()
        now = utc_now_iso()
        if "mode" in self._conversation_columns:
            await self.db.execute(
                "INSERT INTO conversations (id, workspace_id, title, surface, mode, role_id, is_title_customized, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, workspace_id, title, surface, role_id, role_id, is_title_customized, now, now),
            )
        else:
            await self.db.execute(
                "INSERT INTO conversations (id, workspace_id, title, surface, role_id, is_title_customized, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cid, workspace_id, title, surface, role_id, is_title_customized, now, now),
            )
        await self.db.commit()
        return self._normalize_conversation_row({
            "id": cid,
            "workspace_id": workspace_id,
            "title": title,
            "surface": surface,
            "role_id": role_id,
            "is_pinned": 0,
            "is_title_customized": is_title_customized,
            "created_at": now,
            "updated_at": now,
            "last_message": "",
        })

    async def list_conversations(self, workspace_id: str) -> list[dict]:
        rows = await self._fetchall(
            "SELECT c.*, "
            "("
            "  SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            "  ORDER BY m.created_at DESC LIMIT 1"
            ") AS last_message "
            "FROM conversations c "
            "WHERE c.workspace_id=? "
            "ORDER BY c.is_pinned DESC, c.updated_at DESC",
            (workspace_id,),
        )
        return [self._normalize_conversation_row(row) for row in rows]

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        row = await self._fetchone(
            "SELECT c.*, "
            "("
            "  SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
            "  ORDER BY m.created_at DESC LIMIT 1"
            ") AS last_message "
            "FROM conversations c WHERE c.id=?",
            (conversation_id,),
        )
        return self._normalize_conversation_row(row) if row else None

    async def update_conversation(self, conversation_id: str, **kwargs: Union[str, int]) -> Optional[dict]:
        """更新对话字段（title, role_id, is_pinned, is_title_customized 等）"""
        allowed = {"title", "surface", "is_pinned", "role_id", "is_title_customized"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return await self.get_conversation(conversation_id)

        if "role_id" in fields and "mode" in self._conversation_columns:
            fields["mode"] = fields["role_id"]

        fields["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(
            f"UPDATE conversations SET {set_clause} WHERE id=?",
            (*fields.values(), conversation_id),
        )
        await self.db.commit()
        return await self.get_conversation(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> None:
        await self.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        await self.db.commit()

    # ===== Message CRUD =====

    async def add_message(
        self, conversation_id: str, role: str, content: str,
        model: str = "", token_input: int = 0, token_output: int = 0,
        duration_ms: int = 0, metadata: str = "{}",
    ) -> dict:
        mid = gen_id()
        now = utc_now_iso()
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, model, token_input, token_output, duration_ms, metadata, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, conversation_id, role, content, model, token_input, token_output, duration_ms, metadata, now),
        )
        # 同步更新对话的 updated_at
        await self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        await self.db.commit()
        return {
            "id": mid,
            "conversation_id": conversation_id,
            "conversationId": conversation_id,
            "role": role,
            "content": content,
            "model": model,
            "token_input": token_input,
            "tokenInput": token_input,
            "token_output": token_output,
            "tokenOutput": token_output,
            "duration_ms": duration_ms,
            "durationMs": duration_ms,
            "metadata": json.loads(metadata or "{}"),
            "created_at": now,
            "createdAt": now,
        }

    async def update_message(self, message_id: str, **kwargs: Union[str, int]) -> Optional[dict]:
        allowed = {"content", "model", "token_input", "token_output", "duration_ms", "metadata"}
        fields: dict[str, Union[str, int]] = {}
        for key, value in kwargs.items():
            if key not in allowed:
                continue
            if key == "metadata" and not isinstance(value, str):
                fields[key] = json.dumps(value, ensure_ascii=False)
            else:
                fields[key] = value

        if not fields:
            return await self.get_message(message_id)

        set_clause = ", ".join(f"{key}=?" for key in fields)
        await self.db.execute(
            f"UPDATE messages SET {set_clause} WHERE id=?",
            (*fields.values(), message_id),
        )
        await self.db.execute(
            "UPDATE conversations SET updated_at=? WHERE id=("
            "SELECT conversation_id FROM messages WHERE id=?"
            ")",
            (utc_now_iso(), message_id),
        )
        await self.db.commit()
        return await self.get_message(message_id)

    @staticmethod
    def _normalize_message_row(row: dict) -> dict:
        raw_metadata = row.get("metadata") or "{}"
        metadata: dict = {}
        if isinstance(raw_metadata, str):
            try:
                parsed = json.loads(raw_metadata)
                metadata = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                metadata = {}
        elif isinstance(raw_metadata, dict):
            metadata = raw_metadata

        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "conversationId": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row.get("model") or "",
            "token_input": int(row.get("token_input") or 0),
            "tokenInput": int(row.get("token_input") or 0),
            "token_output": int(row.get("token_output") or 0),
            "tokenOutput": int(row.get("token_output") or 0),
            "duration_ms": int(row.get("duration_ms") or 0),
            "durationMs": int(row.get("duration_ms") or 0),
            "metadata": metadata,
            "created_at": row["created_at"],
            "createdAt": row["created_at"],
        }

    async def get_message(self, message_id: str) -> Optional[dict]:
        row = await self._fetchone("SELECT * FROM messages WHERE id=?", (message_id,))
        return self._normalize_message_row(row) if row else None

    async def list_messages(self, conversation_id: str) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
            (conversation_id,),
        )
        return [self._normalize_message_row(row) for row in rows]

    # ===== Agent Run History =====

    @staticmethod
    def _normalize_agent_step_row(row: dict) -> dict:
        raw_metadata = row.get("metadata") or "{}"
        metadata: dict = {}
        if isinstance(raw_metadata, str):
            try:
                parsed = json.loads(raw_metadata)
                metadata = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                metadata = {}
        elif isinstance(raw_metadata, dict):
            metadata = raw_metadata

        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "runId": row["run_id"],
            "index": int(row["step_index"]),
            "step_index": int(row["step_index"]),
            "step_key": row["step_key"],
            "description": row["description"],
            "status": row.get("status") or "pending",
            "result": row.get("result") or "",
            "error": row.get("error") or "",
            "tool_name": row.get("tool_name") or "",
            "toolName": row.get("tool_name") or "",
            "metadata": metadata,
            "started_at": row.get("started_at"),
            "startedAt": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "completedAt": row.get("completed_at"),
            "created_at": row.get("created_at"),
            "createdAt": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "updatedAt": row.get("updated_at"),
        }

    def _normalize_agent_run_row(self, row: dict, steps: Optional[list[dict]] = None) -> dict:
        raw_params = row.get("params") or "{}"
        params: dict = {}
        if isinstance(raw_params, str):
            try:
                parsed = json.loads(raw_params)
                params = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                params = {}
        elif isinstance(raw_params, dict):
            params = raw_params

        raw_final_result = row.get("final_result") or "{}"
        final_result: dict = {}
        if isinstance(raw_final_result, str):
            try:
                parsed = json.loads(raw_final_result)
                final_result = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                final_result = {}
        elif isinstance(raw_final_result, dict):
            final_result = raw_final_result

        raw_message_history = row.get("message_history") or "[]"
        message_history_count = 0
        if isinstance(raw_message_history, (bytes, bytearray)):
            raw_message_history = raw_message_history.decode("utf-8", errors="ignore")
        if isinstance(raw_message_history, str):
            try:
                parsed = json.loads(raw_message_history)
                if isinstance(parsed, list):
                    message_history_count = len(parsed)
            except json.JSONDecodeError:
                message_history_count = 0
        elif isinstance(raw_message_history, list):
            message_history_count = len(raw_message_history)

        normalized_steps = steps if steps is not None else []
        return {
            "id": row["id"],
            "run_id": row["id"],
            "runId": row["id"],
            "conversation_id": row.get("conversation_id"),
            "conversationId": row.get("conversation_id"),
            "surface": row.get("surface") or "agent",
            "role_id": row["role_id"],
            "roleId": row["role_id"],
            "continue_from_run_id": row.get("continue_from_run_id") or "",
            "continueFromRunId": row.get("continue_from_run_id") or "",
            "continue_mode": row.get("continue_mode") or "",
            "continueMode": row.get("continue_mode") or "",
            "skill_id": row.get("skill_id") or "",
            "skillId": row.get("skill_id") or "",
            "skill_name": row.get("skill_name") or "",
            "skillName": row.get("skill_name") or "",
            "query": row.get("query") or "",
            "params": params,
            "status": row.get("status") or "pending",
            "model": row.get("model") or "",
            "llm_profile_id": row.get("llm_profile_id") or "",
            "llmProfileId": row.get("llm_profile_id") or "",
            "message_history_count": message_history_count,
            "messageHistoryCount": message_history_count,
            "final_result": final_result,
            "finalResult": final_result,
            "error": row.get("error") or "",
            "steps": normalized_steps,
            "started_at": row.get("started_at"),
            "startedAt": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "completedAt": row.get("completed_at"),
            "created_at": row.get("created_at"),
            "createdAt": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "updatedAt": row.get("updated_at"),
        }

    async def create_agent_run(
        self,
        run_id: str,
        role_id: str,
        query: str,
        params: Optional[dict] = None,
        conversation_id: Optional[str] = None,
        continue_from_run_id: Optional[str] = None,
        continue_mode: str = "",
        skill_id: Optional[str] = None,
        skill_name: Optional[str] = None,
        model: str = "",
        llm_profile_id: Optional[str] = None,
        message_history: Optional[Union[str, bytes, list, dict]] = None,
        status: str = "pending",
        surface: str = "agent",
        started_at: Optional[str] = None,
    ) -> dict:
        now = utc_now_iso()
        await self.db.execute(
            "INSERT OR REPLACE INTO agent_runs ("
            "id, conversation_id, role_id, surface, continue_from_run_id, continue_mode, skill_id, skill_name, query, params, "
            "status, model, llm_profile_id, message_history, final_result, error, started_at, completed_at, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                conversation_id,
                role_id,
                surface,
                continue_from_run_id,
                continue_mode,
                skill_id,
                skill_name,
                query,
                json.dumps(params or {}, ensure_ascii=False),
                status,
                model,
                llm_profile_id,
                self._to_json_text(message_history, default="[]"),
                "{}",
                "",
                started_at,
                None,
                now,
                now,
            ),
        )
        await self.db.commit()
        run = await self.get_agent_run(run_id)
        if run is None:
            raise RuntimeError("failed to create agent run")
        return run

    async def update_agent_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        skill_id: Optional[str] = None,
        skill_name: Optional[str] = None,
        continue_from_run_id: Optional[str] = None,
        continue_mode: Optional[str] = None,
        message_history: Optional[Union[str, bytes, list, dict]] = None,
        final_result: Optional[dict] = None,
        error: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> Optional[dict]:
        fields: dict[str, object] = {}
        if status is not None:
            fields["status"] = status
        if skill_id is not None:
            fields["skill_id"] = skill_id
        if skill_name is not None:
            fields["skill_name"] = skill_name
        if continue_from_run_id is not None:
            fields["continue_from_run_id"] = continue_from_run_id
        if continue_mode is not None:
            fields["continue_mode"] = continue_mode
        if message_history is not None:
            fields["message_history"] = self._to_json_text(message_history, default="[]")
        if final_result is not None:
            fields["final_result"] = json.dumps(final_result, ensure_ascii=False)
        if error is not None:
            fields["error"] = error
        if started_at is not None:
            fields["started_at"] = started_at
        if completed_at is not None:
            fields["completed_at"] = completed_at
        if not fields:
            return await self.get_agent_run(run_id)

        fields["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{key}=?" for key in fields)
        await self.db.execute(
            f"UPDATE agent_runs SET {set_clause} WHERE id=?",
            (*fields.values(), run_id),
        )
        await self.db.commit()
        return await self.get_agent_run(run_id)

    async def upsert_agent_run_step(
        self,
        run_id: str,
        step_index: int,
        step_key: str,
        description: str,
        *,
        status: str = "pending",
        result: str = "",
        error: str = "",
        tool_name: str = "",
        metadata: Optional[dict] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> dict:
        existing = await self._fetchone(
            "SELECT id FROM agent_run_steps WHERE run_id=? AND step_index=?",
            (run_id, step_index),
        )
        now = utc_now_iso()
        payload = (
            step_key,
            description,
            status,
            result,
            error,
            tool_name,
            json.dumps(metadata or {}, ensure_ascii=False),
            started_at,
            completed_at,
            now,
        )
        if existing:
            await self.db.execute(
                "UPDATE agent_run_steps SET step_key=?, description=?, status=?, result=?, error=?, tool_name=?, metadata=?, "
                "started_at=?, completed_at=?, updated_at=? WHERE run_id=? AND step_index=?",
                (*payload, run_id, step_index),
            )
        else:
            await self.db.execute(
                "INSERT INTO agent_run_steps (id, run_id, step_index, step_key, description, status, result, error, tool_name, "
                "metadata, started_at, completed_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gen_id(),
                    run_id,
                    step_index,
                    *payload[:-1],
                    now,
                    now,
                ),
            )
        await self.db.commit()
        step_row = await self._fetchone(
            "SELECT * FROM agent_run_steps WHERE run_id=? AND step_index=?",
            (run_id, step_index),
        )
        if not step_row:
            raise RuntimeError("failed to upsert agent run step")
        return self._normalize_agent_step_row(step_row)

    async def list_agent_run_steps(self, run_id: str) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM agent_run_steps WHERE run_id=? ORDER BY step_index ASC",
            (run_id,),
        )
        return [self._normalize_agent_step_row(row) for row in rows]

    async def get_agent_run(self, run_id: str) -> Optional[dict]:
        row = await self._fetchone("SELECT * FROM agent_runs WHERE id=?", (run_id,))
        if not row:
            return None
        steps = await self.list_agent_run_steps(run_id)
        return self._normalize_agent_run_row(row, steps)

    async def list_agent_runs_for_conversation(self, conversation_id: str, statuses: Optional[list] = None) -> list[dict]:
        """返回某对话下指定状态的 agent_runs（不含 steps，轻量查询）。"""
        if statuses is None:
            statuses = ["completed", "failed", "cancelled"]
        placeholders = ",".join("?" for _ in statuses)
        rows = await self._fetchall(
            f"SELECT * FROM agent_runs WHERE conversation_id=? AND status IN ({placeholders}) ORDER BY created_at ASC",
            (conversation_id, *statuses),
        )
        return [self._normalize_agent_run_row(row) for row in rows]

    async def get_agent_run_message_history(self, run_id: str) -> str:
        row = await self._fetchone(
            "SELECT message_history FROM agent_runs WHERE id=?",
            (run_id,),
        )
        if not row:
            return "[]"
        return str(row.get("message_history") or "[]")

    async def get_latest_agent_message_history(
        self,
        conversation_id: Optional[str],
        role_id: str,
        *,
        exclude_run_id: Optional[str] = None,
    ) -> str:
        if not conversation_id or not role_id:
            return "[]"

        conditions = [
            "conversation_id=?",
            "role_id=?",
            "message_history IS NOT NULL",
            "TRIM(message_history) <> ''",
            "message_history <> '[]'",
        ]
        params: list[str] = [conversation_id, role_id]
        if exclude_run_id:
            conditions.append("id <> ?")
            params.append(exclude_run_id)

        row = await self._fetchone(
            "SELECT message_history FROM agent_runs "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY updated_at DESC LIMIT 1",
            tuple(params),
        )
        if not row:
            return "[]"
        return str(row.get("message_history") or "[]")

    # ===== Procurement Records =====

    async def add_procurement_record(self, record: dict) -> str:
        rid = gen_id()
        await self.db.execute(
            "INSERT INTO procurement_records (id, source_file, source_file_id, category, item_name, supplier, "
            "unit_price, quantity, total_price, currency, procurement_date, contract_terms, raw_text, confidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, record["source_file"], record.get("source_file_id"), record["category"],
             record["item_name"], record.get("supplier"), record.get("unit_price"),
             record.get("quantity"), record.get("total_price"), record.get("currency", "CNY"),
             record.get("procurement_date"), record.get("contract_terms", "{}"),
             record.get("raw_text"), record.get("confidence", 0.0)),
        )
        await self.db.commit()
        return rid

    async def search_procurement(
        self, category: Optional[str] = None, supplier: Optional[str] = None,
        item_name: Optional[str] = None, min_price: Optional[float] = None,
        max_price: Optional[float] = None, limit: int = 50,
    ) -> list[dict]:
        """结构化查询采购记录（SQLite 精确检索）"""
        conditions: list[str] = []
        params: list[str | float] = []
        if category:
            conditions.append("category LIKE ?")
            params.append(f"%{category}%")
        if supplier:
            conditions.append("supplier LIKE ?")
            params.append(f"%{supplier}%")
        if item_name:
            conditions.append("item_name LIKE ?")
            params.append(f"%{item_name}%")
        if min_price is not None:
            conditions.append("unit_price >= ?")
            params.append(min_price)
        if max_price is not None:
            conditions.append("unit_price <= ?")
            params.append(max_price)
        where = " AND ".join(conditions) if conditions else "1=1"
        return await self._fetchall(
            f"SELECT * FROM procurement_records WHERE {where} ORDER BY extracted_at DESC LIMIT ?",
            (*params, limit),
        )

    # ===== Know-how Rules =====

    async def add_knowhow_rule(self, category: str, rule_text: str, weight: int = 2, source: str = "user") -> str:
        rid = gen_id()
        now = utc_now_iso()
        await self.db.execute(
            "INSERT INTO knowhow_rules (id, category, rule_text, weight, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (rid, category, rule_text, weight, source, now, now),
        )
        await self.db.commit()
        return rid

    async def list_knowhow_rules(self, category: Optional[str] = None, active_only: bool = True) -> list[dict]:
        conditions = []
        params: list[str] = []
        if active_only:
            conditions.append("is_active=1")
        if category:
            conditions.append("category=?")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "1=1"
        return await self._fetchall(f"SELECT * FROM knowhow_rules WHERE {where} ORDER BY weight DESC, hit_count DESC", params)

    async def increment_knowhow_hit(self, rule_id: str) -> None:
        await self.db.execute("UPDATE knowhow_rules SET hit_count = hit_count + 1 WHERE id=?", (rule_id,))
        await self.db.commit()

    # ===== Settings =====

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        updated_at = utc_now_iso()
        await self.db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?",
            (key, value, updated_at, value, updated_at),
        )
        await self.db.commit()

    # ===== PPT Imports =====

    async def record_ppt_import(self, file_name: str, file_hash: str, file_size: int, slide_count: int) -> str:
        """记录 PPT 导入，返回 import_id。若 hash 已存在则返回已有记录 ID"""
        existing = await self._fetchone("SELECT id FROM ppt_imports WHERE file_hash=?", (file_hash,))
        if existing:
            return existing["id"]
        iid = gen_id()
        await self.db.execute(
            "INSERT INTO ppt_imports (id, file_name, file_hash, file_size, slide_count) VALUES (?,?,?,?,?)",
            (iid, file_name, file_hash, file_size, slide_count),
        )
        await self.db.commit()
        return iid

    async def update_ppt_import_status(self, import_id: str, status: str, extracted_count: int = 0) -> None:
        await self.db.execute(
            "UPDATE ppt_imports SET import_status=?, extracted_items_count=? WHERE id=?",
            (status, extracted_count, import_id),
        )
        await self.db.commit()

    async def add_knowledge_chunks(
        self, import_id: str, source_file: str, file_type: str, chunks: list[dict],
    ) -> int:
        rows = []
        created_at = utc_now_iso()
        for chunk in chunks:
            content = str(chunk.get("content") or "").strip()
            if not content:
                continue
            rows.append((
                str(chunk.get("id") or gen_id()),
                import_id,
                source_file,
                file_type,
                int(chunk.get("slide_index") or 0),
                str(chunk.get("chunk_type") or "text"),
                int(chunk.get("chunk_index") or 0),
                chunk.get("char_start"),
                chunk.get("char_end"),
                content,
                created_at,
            ))

        if not rows:
            return 0

        await self.db.executemany(
            "INSERT INTO knowledge_chunks (id, import_id, source_file, file_type, slide_index, chunk_type, "
            "chunk_index, char_start, char_end, content, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        await self.db.commit()
        return len(rows)

    async def delete_knowledge_chunks(
        self, import_id: Optional[str] = None, source_file: Optional[str] = None,
    ) -> int:
        conditions: list[str] = []
        params: list[str] = []
        if import_id:
            conditions.append("import_id=?")
            params.append(import_id)
        if source_file:
            conditions.append("source_file=?")
            params.append(source_file)
        if not conditions:
            return 0

        cursor = await self.db.execute(
            f"DELETE FROM knowledge_chunks WHERE {' AND '.join(conditions)}",
            params,
        )
        await self.db.commit()
        return cursor.rowcount

    async def count_knowledge_chunks(
        self, import_id: Optional[str] = None, source_file: Optional[str] = None,
    ) -> int:
        conditions: list[str] = []
        params: list[str] = []
        if import_id:
            conditions.append("import_id=?")
            params.append(import_id)
        if source_file:
            conditions.append("source_file=?")
            params.append(source_file)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        row = await self._fetchone(
            f"SELECT COUNT(*) AS cnt FROM knowledge_chunks{where}",
            tuple(params),
        )
        return int(row["cnt"]) if row else 0

    async def search_knowledge_chunks(self, keywords: list[str], limit: int = 10) -> list[dict]:
        terms = [term.strip() for term in keywords if term and term.strip()]
        if not terms:
            return []

        score_parts: list[str] = []
        score_params: list[object] = []
        where_parts: list[str] = []
        where_params: list[str] = []

        for index, term in enumerate(terms):
            pattern = f"%{term}%"
            content_weight = max(1, 4 - index)
            file_weight = max(1, content_weight - 1)
            score_parts.append("CASE WHEN content LIKE ? THEN ? ELSE 0 END")
            score_params.extend([pattern, content_weight])
            score_parts.append("CASE WHEN source_file LIKE ? THEN ? ELSE 0 END")
            score_params.extend([pattern, file_weight])
            where_parts.append("content LIKE ?")
            where_params.append(pattern)
            where_parts.append("source_file LIKE ?")
            where_params.append(pattern)

        sql = (
            "SELECT id, import_id, source_file, file_type, slide_index, chunk_type, chunk_index, "
            "char_start, char_end, content, "
            f"({' + '.join(score_parts)}) AS match_score "
            "FROM knowledge_chunks "
            f"WHERE {' OR '.join(where_parts)} "
            "ORDER BY match_score DESC, chunk_index ASC, created_at DESC LIMIT ?"
        )
        return await self._fetchall(sql, [*score_params, *where_params, limit])

    async def list_unindexed_imports(self, limit: int = 5) -> list[dict]:
        return await self._fetchall(
            "SELECT p.id, p.file_name, p.import_status, p.imported_at "
            "FROM ppt_imports p "
            "LEFT JOIN knowledge_chunks kc ON kc.import_id = p.id "
            "GROUP BY p.id "
            "HAVING COUNT(kc.id) = 0 "
            "ORDER BY p.imported_at DESC LIMIT ?",
            (limit,),
        )

    # ===== Skill Usage Logs =====

    async def log_skill_usage(
        self, skill_id: str, conversation_id: str = "", input_summary: str = "",
        output_summary: str = "", success: bool = True, duration_ms: int = 0,
    ) -> str:
        lid = gen_id()
        await self.db.execute(
            "INSERT INTO skill_usage_logs (id, skill_id, conversation_id, input_summary, output_summary, success, duration_ms) "
            "VALUES (?,?,?,?,?,?,?)",
            (lid, skill_id, conversation_id, input_summary, output_summary, int(success), duration_ms),
        )
        await self.db.commit()
        return lid

    # ===== 内部辅助方法 =====

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: Union[tuple, list] = ()) -> list[dict]:
        cursor = await self.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _to_json_text(value: Optional[Union[str, bytes, list, dict]], *, default: str) -> str:
        if value is None:
            return default
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore") or default
        if isinstance(value, str):
            return value or default
        return json.dumps(value, ensure_ascii=False)


# 全局单例
storage = StorageService()
