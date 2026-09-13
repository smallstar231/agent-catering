# 历史会话迁移脚本：JSON 文件 → SQLite
# 背景：项目曾有两套会话存储并存 —— app.py(Streamlit) 用 file_handler 写 JSON 文件，
#       api_service(Vue) 用 session_store 写 SQLite。两者数据互不可见，且 JSON 版缺
#       updated_at 修复（加载历史会话会刷新时间戳、导致列表顺序跳动）。
#       现 app.py 已统一改用 session_store，故需把历史 JSON 会话一次性导入 SQLite。
#
# 特性：
#   · 幂等：已存在的 session_id 跳过（可反复运行）
#   · 保真：原样保留 created_at / updated_at / round_count / title，不伪造时间
#   · 归属：默认写入 user_id="default"（与 app.py 本入口一致）
#   · 只增不改：不删除、不覆盖既有 SQLite 记录
#
# 用法：
#   python -m utils.migrate_json_sessions              # 执行迁移
#   python -m utils.migrate_json_sessions --dry-run    # 只预览，不写库
#   python -m utils.migrate_json_sessions --archive    # 迁移后把 JSON 移入 _legacy_json/
#   （也可直接 python utils/migrate_json_sessions.py，见下方 sys.path 处理）

import os
import sys
import json
import glob
import shutil

# 允许"直接运行"也能找到项目内包；惯例同 rag/* 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.path_tool import get_abs_path
from utils.logger_handler import logger
import utils.session_store as ss

# 迁移来源目录 = SQLite 库所在目录（由 agent.yml 的 session_save_dir 决定，
# 不能从 session_store 的 _DB_REL_PATH 常量推导 —— 那个常量只是相对默认值）。
_SRC_DIR = os.path.dirname(ss._db_path())
_ARCHIVE_SUBDIR = "_legacy_json"


def _load_json(path: str) -> dict | None:
    """读取单个 JSON 存档；损坏/结构不符返回 None（不中断整批迁移）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"[migrate]读取失败，跳过 {os.path.basename(path)}：{str(e)[:100]}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        logger.warning(f"[migrate]结构不符，跳过 {os.path.basename(path)}")
        return None
    return data


def migrate(user_id: str = "default", dry_run: bool = False) -> dict:
    """把 data/sessions/*.json 导入 SQLite。返回统计字典。"""
    src_dir = _SRC_DIR
    files = sorted(glob.glob(os.path.join(src_dir, "*.json")))
    stat = {"total": len(files), "imported": 0, "skipped_exists": 0, "skipped_bad": 0, "messages": 0}
    if not files:
        logger.info(f"[migrate]未发现待迁移的 JSON（目录 {src_dir}）")
        return stat

    # 已有库内 session_id（用于幂等判断）
    conn = ss._connect()
    try:
        existing = {r["id"] for r in conn.execute("SELECT id FROM sessions").fetchall()}
        for path in files:
            name = os.path.basename(path)
            data = _load_json(path)
            if data is None:
                stat["skipped_bad"] += 1
                continue
            sid = str(data.get("id") or os.path.splitext(name)[0])
            if sid in existing:
                stat["skipped_exists"] += 1
                continue

            messages = [m for m in data["messages"] if isinstance(m, dict)]
            title = data.get("title") or sid
            created_at = data.get("created_at") or ""
            updated_at = data.get("updated_at") or created_at
            round_count = int(data.get("round_count") or 0)

            if dry_run:
                logger.info(f"[migrate][dry-run]将导入 {sid}｜{len(messages)} 条消息｜{title[:20]}")
                stat["imported"] += 1
                stat["messages"] += len(messages)
                continue

            conn.execute(
                """INSERT INTO sessions(id,user_id,title,created_at,updated_at,round_count)
                   VALUES(?,?,?,?,?,?)""",
                (sid, user_id, title, created_at, updated_at, round_count),
            )
            conn.executemany(
                "INSERT INTO messages(session_id, role, content, ts) VALUES(?,?,?,?)",
                [(sid, m.get("role", "user"), m.get("content", ""), updated_at) for m in messages],
            )
            existing.add(sid)
            stat["imported"] += 1
            stat["messages"] += len(messages)
        if not dry_run:
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[migrate]迁移失败并回滚：{str(e)[:200]}")
        raise
    finally:
        conn.close()
    return stat


def archive_jsons() -> int:
    """把已迁移的 JSON 移入 data/sessions/_legacy_json/（不删除，可随时取回）"""
    src_dir = _SRC_DIR
    dst_dir = os.path.join(src_dir, _ARCHIVE_SUBDIR)
    files = sorted(glob.glob(os.path.join(src_dir, "*.json")))
    if not files:
        return 0
    os.makedirs(dst_dir, exist_ok=True)
    moved = 0
    for path in files:
        dst = os.path.join(dst_dir, os.path.basename(path))
        if os.path.exists(dst):  # 归档目录已有同名，避免覆盖
            continue
        shutil.move(path, dst)
        moved += 1
    logger.info(f"[migrate]已归档 {moved} 个 JSON 到 {dst_dir}")
    return moved


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv
    _do_archive = "--archive" in sys.argv
    print(f"源目录: {_SRC_DIR}")
    print(f"目标库: {ss._db_path()}")
    print(f"模式  : {'dry-run（不写库）' if _dry else '正式迁移'}\n")

    _stat = migrate(dry_run=_dry)
    print("迁移统计:")
    for k, v in _stat.items():
        print(f"  {k:16} = {v}")

    if not _dry and _do_archive and _stat["skipped_bad"] == 0:
        _moved = archive_jsons()
        print(f"\n已归档 JSON 文件: {_moved} 个 → {_ARCHIVE_SUBDIR}/")
    elif not _dry and _do_archive:
        print("\n⚠️ 存在读取失败的 JSON，已跳过归档（避免误移未迁移文件）")

    # 迁移后核对：default 用户的会话列表
    _rows = ss.load_saved_sessions(user_id="default")
    print(f"\ndefault 用户当前会话数: {len(_rows)}")
    for _r in _rows[:10]:
        print(f"  · {_r['id']}  {_r['updated_at']}  {_r['round_count']}轮  {_r['title'][:20]}")
