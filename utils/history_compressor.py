# 会话历史压缩模块
# 功能：在把历史消息喂给 LLM 之前，按字符预算压缩——解决"长对话全量回传导致上下文超限/token 浪费"
# 被 agent/react_agent.py 调用（execute_stream 入口）
# 设计参考 PAI-RAG 的 AgentMessageManager 多级压缩思路，但适配本项目形态：
#   - 本项目前端回传的 history 只有 user/assistant 纯文本（工具轮不回流），因此没有"截断 tool 输出"这一级；
#   - 核心策略：超预算时从最旧整轮丢弃 → 保护最近 N 轮 + 末条 assistant/当前 user 永不丢 → 极端时截断最旧保留文本。
# 纯函数、无 IO，可直接单测。

import os
import sys

# 允许"直接运行"（python utils/history_compressor.py）也能找到项目内包；
# 惯例同 rag/* 模块。用 python -m utils.history_compressor 时此行亦无副作用。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_handler import conv_conf  # 压缩参数配置
from utils.logger_handler import logger      # 日志记录器

# 压缩参数默认值（从 config/conv.yml 读取，缺省时回退以下常量）
# 注：compress_history 返回的是**新列表 + 每条消息的浅拷贝**，绝不修改入参 history。
DEFAULT_CHAR_BUDGET = 8000
DEFAULT_PROTECTED_ROUNDS = 6
DEFAULT_ASSISTANT_TRUNCATE = 400
DEFAULT_MARKER = "...[已截断]"


def _cfg(key: str, default):
    """从 conv_conf 读取配置项，缺键或类型异常时回退默认值"""
    try:
        val = conv_conf.get(key, default)
        return default if val is None else val
    except Exception:
        return default


def estimate_chars(message: dict) -> int:
    """
    估算单条消息的字符成本
    入参：message - {role, content} 消息
    返回：字符数（近似 token 数，中文 1 字 ≈ 1-2 token，这里保守按字符计）
    """
    content = message.get("content") or ""
    return len(content) + 8  # 8 = 角色/结构开销近似


def total_chars(messages: list) -> int:
    """计算整段历史的总字符成本"""
    return sum(estimate_chars(m) for m in messages)


def _rounds_of(messages: list) -> list:
    """
    把扁平消息列表切分为"轮"：user + 紧随其后的 assistant 视为一轮
    入参：messages - [{role, content}, ...]
    返回：轮列表 [[msg, msg, ...], ...]（每轮可能 1-2 条）
    """
    rounds: list[list] = []
    i = 0
    n = len(messages)
    while i < n:
        if messages[i].get("role") == "user":
            # user 开头：把紧跟其后的 assistant 并入同轮
            if i + 1 < n and messages[i + 1].get("role") == "assistant":
                rounds.append([messages[i], messages[i + 1]])
                i += 2
            else:
                rounds.append([messages[i]])
                i += 1
        else:
            # assistant 开头（异常顺序，通常不会）：单条成轮
            rounds.append([messages[i]])
            i += 1
    return rounds


def _truncate_text(text: str, limit: int, marker: str) -> str:
    """把文本截到 limit 字符并在末尾加截断标记（仅在超长时）"""
    if len(text) <= limit:
        return text
    return text[:limit] + marker


def compress_history(history: list, budget_chars: int | None = None) -> list:
    """
    压缩会话历史（核心入口）
    入参：
        history       - 历史消息列表 [{role, content}, ...]，role 为 user/assistant
        budget_chars  - 字符预算；None 时使用 config/conv.yml 的 history_char_budget
    返回：
        压缩后的消息列表。若原长度未超预算则原样返回。
    策略（按需逐级执行）：
        1. 总长 ≤ 预算 → 原样返回
        2. 从最旧整轮丢弃，直到 ≤ 预算 或 只剩最近 protected_rounds 轮
        3. 无论丢多少，末条 assistant 与最后一条 user（当前问题）恒保留
        4. 仍超预算 → 对最旧保留 assistant 截断到 assistant_truncate_chars
    """
    if not history:
        return history

    if budget_chars is None:
        budget_chars = _cfg("history_char_budget", DEFAULT_CHAR_BUDGET)
    protected_rounds = _cfg("protected_rounds", DEFAULT_PROTECTED_ROUNDS)
    assistant_truncate = _cfg("assistant_truncate_chars", DEFAULT_ASSISTANT_TRUNCATE)
    marker = _cfg("truncate_marker", DEFAULT_MARKER)

    if total_chars(history) <= budget_chars:
        return history

    # ---- 第一步：保留最近 protected_rounds 轮（含最后一条 user 及其回复），其余整轮丢弃 ----
    rounds = _rounds_of(history)
    protected = rounds[-protected_rounds:] if len(rounds) > protected_rounds else rounds
    # 末条 assistant 与最后一条 user 所在轮必须保留：
    # 若它们位于被保护的最近 protected_rounds 之外（极端超长单条），强制并入保护集
    last_user_round = None
    last_asst_round = None
    for r in rounds:
        for m in r:
            if m.get("role") == "user":
                last_user_round = r
            elif m.get("role") == "assistant":
                last_asst_round = r
    for r in (last_user_round, last_asst_round):
        if r is not None and r not in protected:
            protected.append(r)

    # ★ 浅拷贝每条消息：下面第二步会就地改 result[i]["content"]，
    #   若直接引用入参里的字典对象，截断会"写回调用方的 history"，
    #   违反本模块"纯函数、无 IO"的承诺（实测入参 602→408 字符）；
    #   且会使第 145 行日志里的"压缩前字数"记成已被截断后的值。
    result = [dict(m) for r in protected for m in r]

    # ---- 第二步：若受保护轮仍超预算（极端超长），对受保护范围内最旧 assistant 截断 ----
    # 恒不截断：最后一条 user（当前问题）与末条 assistant 的完整性
    last_user_idx = last_asst_idx = None
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user" and last_user_idx is None:
            last_user_idx = i
        if result[i].get("role") == "assistant" and last_asst_idx is None:
            last_asst_idx = i
    if last_asst_idx is None:  # 没有 assistant 时只保护最后 user
        last_asst_idx = -1

    if total_chars(result) > budget_chars:
        for i, m in enumerate(result):
            if i == last_user_idx or i == last_asst_idx:
                continue  # 保护完整性，不截
            if m.get("role") == "assistant" and total_chars(result) > budget_chars:
                m["content"] = _truncate_text(m.get("content", ""), assistant_truncate, marker)

    if total_chars(result) > budget_chars:
        logger.warning(
            f"[compress_history]已保留最近 {len(protected)} 轮并截断旧 assistant，"
            f"仍 {total_chars(result)}字 > 预算 {budget_chars}（尽力而为，保护末轮语义优先）"
        )

    logger.info(
        f"[compress_history]压缩完成：{total_chars(history)}字 → {total_chars(result)}字 "
        f"(预算 {budget_chars}, 保留 {len(result)} 条)"
    )
    return result


if __name__ == '__main__':
    # 直接运行此文件时，测试压缩逻辑（同时作为回归用例）
    # ★ 用 8 轮（> protected_rounds 默认 6），确保"压缩真会丢轮"；
    #   旧版自测只有 4 轮 → 一条轮都不丢 → len 不变 → "压缩应减少条数"断言必然失败。
    _h = [
        m
        for i in range(1, 9)
        for m in (
            {"role": "user", "content": f"第{i}问" + "长" * 300},
            {"role": "assistant", "content": f"第{i}答" + "长" * 600},
        )
    ]
    _budget = 5000

    _snapshot = [dict(m) for m in _h]        # 入参快照，用于回归"不污染调用方"
    _chars_before = total_chars(_h)          # 必须在调用前算

    _out = compress_history(_h, budget_chars=_budget)

    print("压缩前条数:", len(_h), "字符:", _chars_before)
    print("压缩后条数:", len(_out), "字符:", total_chars(_out))
    print("调用后入参条数:", len(_h), "字符:", total_chars(_h),
          "（应与压缩前一致，证明未被就地修改）")
    for m in _out:
        print(" ", m["role"], m["content"][:30], "...")

    assert _h == _snapshot, "★ 入参 history 不应被就地修改（纯函数契约）"
    assert total_chars(_h) == _chars_before, "★ 入参字符数不应被压缩改变"
    assert len(_out) < len(_h), "压缩应减少条数"
    assert any(m.get("role") == "user" for m in _out), "应保留最后一条 user"
    assert total_chars(_out) <= _budget, "截断后应回到预算内"
    print("OK（含回归：入参未被污染）")
