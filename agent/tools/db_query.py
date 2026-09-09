# 只读数据库查询工具
# 功能：让 Agent 自己写 SQL 查询应用数据库（苍穹外卖 sky_take_out），**只读**。
# 背景：Agent 应能基于真实业务数据回答问题（如"最近卖得最好的菜""某订单金额"），
#       但不能通过本工具修改/删除数据。
# 安全设计（多层只读保证）：
#   1. SQL 语法层：仅允许以 SELECT 开头的单条查询；禁多语句(;) / 注释混淆 / 危险表。
#   2. 表白名单：只允许查询业务表，禁 employee(管理员/密码)、user(用户隐私) 等敏感表。
#   3. 行数上限：强制 LIMIT（缺省补 100，拒绝无 LIMIT 且可能全表拉取的大查询）。
#   4. 连接层：用 .env 配的只读 DB 账号（无则回退提示配置），MySQL 权限层兜底。
#   5. 超时/结果截断，绝不向 Agent 抛异常。

import os
import re
from typing import Optional
from langchain_core.tools import tool
from utils.logger_handler import logger
from utils import config_handler  # 触发 .env 加载

# ---- 配置（根 .env）----
# DB_READ_HOST / DB_READ_PORT / DB_READ_USER / DB_READ_PASSWORD / DB_READ_NAME
_DEF_HOST = "localhost"
_DEF_PORT = 3306
_DEF_USER = "root"          # 本地学习默认；生产务必换最小权限只读账号
_DEF_PASSWORD = "123456"
_DEF_DB = "sky_take_out"


def _cfg(key: str, default: str) -> str:
    v = os.getenv(key, "").strip()
    return v or default


def _connect_params() -> dict:
    return {
        "host": _cfg("DB_READ_HOST", _DEF_HOST),
        "port": int(_cfg("DB_READ_PORT", str(_DEF_PORT))),
        "user": _cfg("DB_READ_USER", _DEF_USER),
        "password": _cfg("DB_READ_PASSWORD", _DEF_PASSWORD),
        "database": _cfg("DB_READ_NAME", _DEF_DB),
        "connect_timeout": 5,
        "read_timeout": 15,
        "charset": "utf8mb4",
    }


# 允许查询的业务表（苍穹外卖 sky_take_out）。不在列表内的表拒绝（防查敏感/系统表）。
_ALLOWED_TABLES = {
    "category", "dish", "dish_flavor", "setmeal", "setmeal_dish",
    "orders", "order_detail", "shopping_cart", "address_book",
}
# 显式禁止的敏感表（即使未来加了权限也不该经本工具暴露）
_FORBIDDEN_TABLES = {"employee", "user"}

# 单次最多返回行数
_MAX_ROWS = 100
# 单元格内容最大长度（防超长字段撑爆上下文）
_MAX_CELL_CHARS = 80


def _extract_tables(sql: str) -> set:
    """从 SQL 中提取所有出现的表名（含 join/子查询的 from/join 后）。"""
    # 去掉字符串字面量，避免 'xxx' 里的词被误当表名
    s = re.sub(r"'[^']*'", "''", sql, flags=re.S)
    s = re.sub(r'"[^"]*"', '""', s, flags=re.S)
    # 去注释
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"--[^\n]*", " ", s)
    tables = set()
    # 匹配 from / join 后的标识符（可带 db. 前缀，取最后一段）
    for m in re.finditer(r"\b(?:from|join)\s+([`]?[\w.]+[`]?)", s, re.I):
        t = m.group(1).strip("`")
        t = t.split(".")[-1]  # 去掉库名前缀
        tables.add(t.lower())
    return tables


def _validate_select(sql: str) -> str:
    """校验 SQL 是否只读安全。通过返回清洗后的 SQL；不通过抛 ValueError。"""
    sql = (sql or "").strip()
    if not sql:
        raise ValueError("SQL 不能为空")
    # 去掉末尾分号（单条语句允许一个结尾分号）
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    # 1) 必须以 SELECT / WITH(仅当内部是 select) 开头 —— 但 WITH 可含 CTE，简化起见只允许 SELECT
    if not re.match(r"^\s*select\b", sql, re.I):
        raise ValueError("仅允许 SELECT 只读查询")
    # 2) 禁多语句：内部再出现分号 = 多语句注入
    if ";" in sql:
        raise ValueError("禁止多语句（一次只能一条查询）")
    # 3) 禁危险关键词（写操作 / 系统调用 / 信息泄露）
    danger = re.findall(
        r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
        r"call|load_file|into\s+outfile|information_schema|mysql\.|"
        r"sleep|benchmark|procedure|execute|sys\.)\b",
        sql, re.I)
    if danger:
        raise ValueError(f"检测到被禁止的 SQL 操作：{danger[0]}")
    # 4) 表白名单
    tables = _extract_tables(sql)
    if not tables:
        raise ValueError("未能识别查询的表（请写清楚 FROM/JOIN 表名）")
    bad = tables & _FORBIDDEN_TABLES
    if bad:
        raise ValueError(f"禁止查询敏感表：{'、'.join(sorted(bad))}")
    unknown = tables - _ALLOWED_TABLES
    if unknown:
        raise ValueError(f"不在允许查询的业务表内：{'、'.join(sorted(unknown))}")
    # 5) 行数上限：无 LIMIT 则补；已有 LIMIT 则校验 ≤ _MAX_ROWS
    limit_m = re.search(r"\blimit\s+(\d+)", sql, re.I)
    if limit_m:
        n = int(limit_m.group(1))
        if n > _MAX_ROWS:
            raise ValueError(f"LIMIT 不能超过 {_MAX_ROWS}")
    else:
        sql += f" LIMIT {_MAX_ROWS}"
    return sql


def _fmt_result(rows: list[tuple], cols: list[str]) -> str:
    """把查询结果格式化为对齐文本，供 Agent 阅读。"""
    if not rows:
        return "（查询成功，0 行结果）"
    # 单元格截断
    def _cell(v):
        if v is None:
            return "NULL"
        s = str(v)
        return s[:_MAX_CELL_CHARS] + "…" if len(s) > _MAX_CELL_CHARS else s
    header = " | ".join(cols)
    lines = [header, "-" * min(len(header), 80)]
    for r in rows[: _MAX_ROWS]:
        lines.append(" | ".join(_cell(c) for c in r))
    lines.append(f"（共 {len(rows)} 行）")
    return "\n".join(lines)


def db_query_sql(sql: str) -> str:
    """执行单条只读 SELECT，返回格式化结果文本。失败返回原因文案，绝不抛给 Agent。"""
    try:
        sql = _validate_select(sql)
    except ValueError as e:
        logger.info(f"[db_query]校验拒绝：{e}")
        return f"【db_query】{e}"

    params = _connect_params()
    try:
        import pymysql
    except ImportError:
        return "【db_query】缺少 pymysql 依赖，无法连接数据库。"
    try:
        conn = pymysql.connect(**params)
    except Exception as e:
        logger.error(f"[db_query]连接数据库失败：{str(e)[:150]}")
        return f"【db_query】连接数据库失败：{str(e)[:120]}（请检查 .env 的 DB_READ_* 配置）"
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        conn.close()
        logger.info(f"[db_query]执行成功：{sql[:80]}… → {len(rows)} 行")
        return f"查询结果：\n{_fmt_result(rows, cols)}"
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        logger.error(f"[db_query]SQL 执行失败：{str(e)[:150]}")
        return f"【db_query】SQL 执行失败：{str(e)[:120]}"


@tool(description=(
    "查询苍穹外卖应用数据库（只读，兜底用）。"
    "【重要-优先级】查菜品/套餐/分类/订单时，必须先用专用工具 "
    "sky_query_dish / sky_query_setmeal / sky_query_category / sky_query_order；"
    "仅当这些专用工具无法满足（例如需要销量排名、金额汇总、跨表 join 等聚合统计）"
    "时才使用本工具。"
    "入参 sql 为一条 SELECT 查询，如 'SELECT name,price FROM dish WHERE status=1 LIMIT 10'。"
    "仅支持只读查询；可查的表：category/dish/dish_flavor/setmeal/setmeal_dish/"
    "orders/order_detail/shopping_cart/address_book。自动限制最多 100 行。"))
def db_query(sql: str) -> str:
    """Agent 自主写只读 SQL 查询业务数据。"""
    logger.info(f"[db_query]收到 SQL：{sql[:120]}")
    return db_query_sql(sql)
