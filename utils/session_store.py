# SQLite 会话存储模块
# 功能：用 SQLite 两张表（sessions / messages）替代 JSON 文件会话存档
# 动机：原 file_handler.save_session_to_disk 把整段对话写 JSON 明文文件，历史不可检索、易损坏；
#       改 SQLite 后支持按会话聚合查询，读写更稳，且为将来"多用户/权限"留好扩展。
# 保持函数签名对齐 file_handler 的 save_session_to_disk/load_saved_sessions/load_session_messages，
# 因此 api_service 可无缝替换，前端 API 形状不变。

import sqlite3
import os
import datetime
from utils.path_tool import get_abs_path
from utils.config_handler import agent_conf
from utils.logger_handler import logger

# 数据库文件位置（相对项目根）
_DB_REL_PATH = "data/agent_sessions.db"

# sqlite3 连接不能跨线程共享；api_service 是单进程多线程(线程池)，
# 这里用"每操作新建连接 + 全局写锁"保证线程安全、避免 check_same_thread 问题。
_write_lock = None  # 惰性初始化

def _lock():
    """返回全局写锁（跨线程互斥，sqlite 单写者）"""
    global _write_lock
    if _write_lock is None:
        import threading
        _write_lock = threading.Lock()
    return _write_lock


def _db_path() -> str:
    """数据库文件绝对路径（可用 agent.yml 的 session_save_dir 改目录）"""
    try:
        d = agent_conf.get("session_save_dir", "data/sessions")
    except Exception:
        d = "data/sessions"
    # 兼容旧路径语义：若配的是目录，则库文件放该目录下
    if d.endswith(".db"):
        return get_abs_path(d)
    return get_abs_path(os.path.join(d, "agent_sessions.db"))


def _connect() -> sqlite3.Connection:
    """新建一个 SQLite 连接，并确保表结构存在"""
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            title TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT,
            round_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            ts TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
    # 旧库迁移：若已存在但缺 user_id 列，先补列（默认 'default'），再建索引
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    if "user_id" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT 'default'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    conn.commit()
    return conn


def save_session_to_disk(messages: list, round_count: int, session_id: str | None = None, save_dir: str = "data/sessions", user_id: str = "default") -> tuple:
    """
    保存/更新会话到 SQLite
    入参：同 file_handler 同名函数（见其文档），save_dir 仅作兼容保留（实际目录由 agent.yml 决定）；
         user_id - 归属用户（用于多用户会话隔离），默认 "default"
    返回：(库文件路径, session_id)
    """
    if not messages:
        return None, None

    now = datetime.datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")

    if not session_id:
        # 默认 id：秒级时间戳 + 用户 + 随机短码，避免多用户同一秒保存时撞 id
        import secrets
        session_id = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{user_id[:6]}{secrets.token_hex(2)}"

    # 取第一条 user 消息作标题（截前 30 字）
    title = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content") or ""
            title = content[:30] + ("..." if len(content) > 30 else "")
            break
    if not title:
        title = session_id

    with _lock():
        conn = _connect()
        try:
            # 会话 upsert（user_id 一并写入；更新时保留原属主，不跨用户覆盖）
            row = conn.execute("SELECT created_at, user_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            created_at = row["created_at"] if row else ts
            owner = row["user_id"] if row else user_id

            # ★ 判断本次是否"真新增/变化了消息"：
            #   只有消息确实变化才刷新 updated_at，否则保留原值。
            #   原因：前端在"点击历史会话/新建会话"前会先 save 一次当前会话（防丢），
            #   若内容未变仍刷新 updated_at，会导致会话时间随点击而跳变，
            #   而不是以"最后一条聊天时间"为准。
            changed = True
            prev_updated = None
            if row:
                prev_updated = row["created_at"]  # 占位，下方查真实 updated_at
            # 读库中已有 updated_at 与消息数，判断内容是否有实质变化
            prev_row = conn.execute("SELECT updated_at FROM sessions WHERE id=?", (session_id,)).fetchone()
            if prev_row and prev_row["updated_at"]:
                prev_updated = prev_row["updated_at"]
                prev_msgs = conn.execute(
                    "SELECT role, content FROM messages WHERE session_id=? ORDER BY id ASC", (session_id,)
                ).fetchall()
                cur_msgs = [(m.get("role", "user"), m.get("content", "")) for m in messages]
                prev_list = [(r["role"], r["content"]) for r in prev_msgs]
                # 逐条比较（顺序敏感）；完全相同 = 无变化
                changed = cur_msgs != prev_list
            new_updated = ts if changed else (prev_updated or ts)

            conn.execute(
                """INSERT INTO sessions(id,user_id,title,created_at,updated_at,round_count)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, updated_at=excluded.updated_at, round_count=excluded.round_count""",
                (session_id, owner, title, created_at, new_updated, round_count),
            )
            # 消息整体替换（先删后插，保证与前端 messages 一致）
            conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            conn.executemany(
                "INSERT INTO messages(session_id, role, content, ts) VALUES(?,?,?,?)",
                [(session_id, m.get("role", "user"), m.get("content", ""), ts) for m in messages],
            )
            conn.commit()
            logger.info(f"[sqlite_session]已保存会话 {session_id}（{len(messages)} 条消息, {round_count} 轮）")
            return _db_path(), session_id
        except Exception as e:
            conn.rollback()
            logger.error(f"[sqlite_session]保存失败：{str(e)}")
            return None, None
        finally:
            conn.close()


def load_saved_sessions(save_dir: str = "data/sessions", user_id: str = "default") -> list[dict]:
    """读取某用户的会话元数据列表（不含消息），按 updated_at 降序"""
    if not os.path.exists(_db_path()):
        return []
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id,user_id,title,created_at,updated_at,round_count FROM sessions WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[sqlite_session]读列表失败：{str(e)}")
        return []


def load_session_messages(filepath: str) -> list | None:
    """
    读取某会话的完整消息列表
    入参：filepath - 兼容旧接口参数。sqlite 模式下我们按"目录内含 session_id"推断：
          传入的是 "目录/会话ID" 或直接库路径；若 filepath 形如 .../sessions/<id>.json 则取 <id>。
    """
    base = os.path.basename(filepath)
    sid = base[:-5] if base.endswith(".json") else base
    return _load_messages_by_id(sid)


def _load_messages_by_id(session_id: str, user_id: str | None = None) -> list | None:
    """按 session_id 读取会话消息（按 id 升序保证时序）。
    若传 user_id，会校验该会话属于该用户，否则返回 None（防越权）。"""
    try:
        conn = _connect()
        try:
            # 归属校验
            if user_id:
                own = conn.execute("SELECT 1 FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
                if not own:
                    return None
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id=? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[sqlite_session]读会话失败：{session_id} - {str(e)}")
        return None


def get_session_messages(session_id: str, user_id: str | None = None) -> list | None:
    """按 session_id 读取（api_service 用）；user_id 用于越权校验"""
    return _load_messages_by_id(session_id, user_id)


def delete_session(session_id: str, user_id: str | None = None) -> bool:
    """删除某会话及其消息。若传 user_id，仅当会话属于该用户时才删。"""
    with _lock():
        try:
            conn = _connect()
            try:
                if user_id:
                    own = conn.execute("SELECT 1 FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
                    if not own:
                        return False  # 不属于该用户，拒绝删除
                conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[sqlite_session]删除失败：{session_id} - {str(e)}")
            return False


if __name__ == '__main__':
    # 直接运行此文件时，测试 SQLite 会话读写
    _p, _sid = save_session_to_disk(
        [{"role": "user", "content": "测试问题"}, {"role": "assistant", "content": "测试回答"}],
        1,
    )
    print("saved:", _p, _sid)
    print("sessions:", load_saved_sessions())
    print("messages:", get_session_messages(_sid))
    delete_session(_sid)
    print("after delete:", load_saved_sessions())
