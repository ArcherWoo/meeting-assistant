"""
SQLite 存储服务 - 统一数据库连接与 Schema 管理
遵循 PRD §13.1 数据库设计，所有表均在 ~/.meeting-assistant/data/main.db 中
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import aiosqlite
from services.runtime_paths import DATA_DIR, DB_PATH

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
    mode          TEXT NOT NULL DEFAULT 'copilot',
    is_pinned     INTEGER DEFAULT 0,
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

-- Prompt templates
CREATE TABLE IF NOT EXISTS prompt_templates (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT DEFAULT '',
    scope          TEXT NOT NULL DEFAULT 'global',
    content        TEXT NOT NULL,
    variables_json TEXT DEFAULT '{}',
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_scope ON prompt_templates(scope);

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
    capabilities  TEXT DEFAULT '[]',
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

    async def initialize(self) -> None:
        """初始化数据库：创建目录、连接、执行 Schema"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA_SQL)
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

    @property
    def db(self) -> aiosqlite.Connection:
        """获取数据库连接（需先调用 initialize）"""
        if not self._db:
            raise RuntimeError("StorageService 未初始化，请先调用 initialize()")
        return self._db

    # ===== Workspace CRUD =====

    async def _ensure_default_workspace(self) -> None:
        """确保存在默认工作区"""
        row = await self._fetchone("SELECT id FROM workspaces LIMIT 1")
        if not row:
            await self.create_workspace("默认工作区", "系统自动创建的默认工作区", "📋")

    async def _ensure_default_roles(self) -> None:
        """确保三个默认角色存在（copilot / builder / agent），均为可编辑/可删除的普通角色"""
        import json as _json
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
                "is_builtin": 0,
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
                "is_builtin": 0,
                "sort_order": 1,
            },
            {
                "id": "agent",
                "name": "Agent",
                "icon": "🤖",
                "description": "分步执行、透明反馈",
                "system_prompt": (
                    "你是一个智能 Agent，能够调用各种工具和技能完成复杂任务。"
                    "请分析用户的需求，选择合适的工具，并逐步执行任务。"
                    "执行过程中保持透明，让用户了解每一步的进展。"
                ),
                "capabilities": _json.dumps(["rag", "skills"]),
                "is_builtin": 0,
                "sort_order": 2,
            },
        ]
        for role in defaults:
            existing = await self._fetchone("SELECT id FROM roles WHERE id=?", (role["id"],))
            if not existing:
                now = utc_now_iso()
                await self.db.execute(
                    "INSERT INTO roles (id, name, icon, description, system_prompt, capabilities, is_builtin, sort_order, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (role["id"], role["name"], role["icon"], role["description"],
                     role["system_prompt"], role["capabilities"], role["is_builtin"],
                     role["sort_order"], now, now),
                )
            else:
                # 若旧记录 is_builtin=1，迁移为可编辑的普通角色
                await self.db.execute(
                    "UPDATE roles SET is_builtin=0 WHERE id=? AND is_builtin=1",
                    (role["id"],),
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
        capabilities: Optional[list] = None,
    ) -> dict:
        import json as _json
        rid = gen_id()
        now = utc_now_iso()
        caps = _json.dumps(capabilities or [])
        # 计算排序值（追加到最后）
        row = await self._fetchone("SELECT MAX(sort_order) AS max_order FROM roles")
        sort_order = (row["max_order"] or 0) + 1 if row else 1
        await self.db.execute(
            "INSERT INTO roles (id, name, icon, description, system_prompt, capabilities, is_builtin, sort_order, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,0,?,?,?)",
            (rid, name, icon, description, system_prompt, caps, sort_order, now, now),
        )
        await self.db.commit()
        return {
            "id": rid, "name": name, "icon": icon, "description": description,
            "system_prompt": system_prompt, "capabilities": capabilities or [],
            "is_builtin": 0, "sort_order": sort_order,
            "created_at": now, "updated_at": now,
        }

    async def update_role(self, role_id: str, **kwargs) -> Optional[dict]:
        import json as _json
        allowed = {"name", "icon", "description", "system_prompt", "capabilities", "sort_order"}
        fields: dict = {}
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "capabilities" and isinstance(v, list):
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
        row = await self._fetchone("SELECT is_builtin FROM roles WHERE id=?", (role_id,))
        if not row:
            return False
        if row["is_builtin"]:
            raise ValueError("内置角色不可删除")
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

    # ===== Conversation CRUD =====

    async def create_conversation(self, workspace_id: str, title: str = "新对话", mode: str = "copilot") -> dict:
        cid = gen_id()
        now = utc_now_iso()
        await self.db.execute(
            "INSERT INTO conversations (id, workspace_id, title, mode, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (cid, workspace_id, title, mode, now, now),
        )
        await self.db.commit()
        return {"id": cid, "workspace_id": workspace_id, "title": title, "mode": mode, "created_at": now, "updated_at": now}

    async def list_conversations(self, workspace_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM conversations WHERE workspace_id=? ORDER BY is_pinned DESC, updated_at DESC",
            (workspace_id,),
        )

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        return await self._fetchone("SELECT * FROM conversations WHERE id=?", (conversation_id,))

    async def update_conversation(self, conversation_id: str, **kwargs: Union[str, int]) -> None:
        """更新对话字段（title, is_pinned 等）"""
        allowed = {"title", "is_pinned", "mode"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        fields["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(
            f"UPDATE conversations SET {set_clause} WHERE id=?",
            (*fields.values(), conversation_id),
        )
        await self.db.commit()

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
        return {"id": mid, "conversation_id": conversation_id, "role": role, "content": content, "created_at": now}

    async def list_messages(self, conversation_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
            (conversation_id,),
        )

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

    async def add_prompt_template(
        self,
        template_id: str,
        name: str,
        description: str,
        scope: str,
        content: str,
        variables_json: str = "{}",
    ) -> str:
        now = utc_now_iso()
        await self.db.execute(
            "INSERT INTO prompt_templates (id, name, description, scope, content, variables_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (template_id, name, description, scope, content, variables_json, now, now),
        )
        await self.db.commit()
        return template_id

    async def get_prompt_template(self, template_id: str) -> Optional[dict]:
        return await self._fetchone("SELECT * FROM prompt_templates WHERE id=?", (template_id,))

    async def list_prompt_templates(self, scope: Optional[str] = None) -> list[dict]:
        if scope:
            return await self._fetchall(
                "SELECT * FROM prompt_templates WHERE scope IN (?, 'global') ORDER BY updated_at DESC, name COLLATE NOCASE ASC",
                (scope,),
            )
        return await self._fetchall(
            "SELECT * FROM prompt_templates ORDER BY updated_at DESC, name COLLATE NOCASE ASC"
        )

    async def update_prompt_template(self, template_id: str, **kwargs: str) -> bool:
        allowed = {"name", "description", "scope", "content", "variables_json"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False

        fields["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{key}=?" for key in fields)
        cursor = await self.db.execute(
            f"UPDATE prompt_templates SET {set_clause} WHERE id=?",
            (*fields.values(), template_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def delete_prompt_template(self, template_id: str) -> bool:
        cursor = await self.db.execute("DELETE FROM prompt_templates WHERE id=?", (template_id,))
        await self.db.commit()
        return cursor.rowcount > 0

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


# 全局单例
storage = StorageService()
