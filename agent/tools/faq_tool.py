# FAQ 精确问答工具
# 功能：从苍穹外卖 FAQ 文档（data/苍穹外卖常见问题FAQ.txt）解析出 Q&A 对，供 Agent 精确命中高频问题
# 为什么单独做：FAQ 是"一问一答整块"，若并入 Chroma 普通分片（chunk≈200字）会把 Q/A 拆散导致语义碎片；
#               高频问题用"精确/子串/词重叠"命中 100% 准确且快，不依赖向量检索。
# 被 agent/react_agent.py 注册为工具（scene=sky 时注册）

import re
from utils.config_handler import agent_conf  # 读取知识库路径配置
from utils.path_tool import get_abs_path
from utils.logger_handler import logger

# FAQ 文档路径（相对项目根），可被 agent.yml 覆盖
_FAQ_REL_PATH = "data/苍穹外卖常见问题FAQ.txt"

# 模块级缓存：{question: {q, a, section}}，首次调用解析一次
_faq_cache: list | None = None
_faq_path_used: str | None = None


def _faq_path() -> str:
    """FAQ 文档绝对路径（支持 agent.yml 覆盖 faq_path）"""
    try:
        p = agent_conf.get("faq_path", _FAQ_REL_PATH)
    except Exception:
        p = _FAQ_REL_PATH
    return get_abs_path(p)


def _norm(s: str) -> str:
    """归一化文本：去空白/标点/全角空格，转小写，用于匹配"""
    s = (s or "").strip().lower()
    # 去常见中文/英文标点与空白（ASCII 方括号单独剔除，避免在字符类内转义告警）
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r"[\s，。？！、；：""''（）()【】,.?!;:]+", "", s)
    return s


def load_faq() -> list:
    """
    解析 FAQ 文档为结构化 Q&A 列表
    返回：list[{q, a, section}]；文件缺失/空时返回空列表（不抛错）。
    格式支持：
        章节标题行（如 "1. 下单与支付"） → section
        Q: xxx  → 开启新问题
        A: xxx  → 答案；A: 后的多行（直到下一个 Q: 或文件尾）继续并入答案
    """
    global _faq_cache, _faq_path_used
    path = _faq_path()
    if _faq_cache is not None and _faq_path_used == path:
        return _faq_cache

    faqs = []
    section = ""
    cur_q = None
    cur_a_lines: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n").strip()
                if not line:
                    continue
                # 章节标题：数字. 标题
                sec_m = re.match(r"^\d+[\.、]\s*(.+)$", line)
                if sec_m and not line.startswith(("Q:", "A:")):
                    # 落库上一个问题
                    if cur_q is not None:
                        faqs.append({"q": cur_q, "a": "\n".join(cur_a_lines).strip(), "section": section})
                        cur_q = None
                        cur_a_lines = []
                    section = sec_m.group(1).strip()
                    continue
                if line.startswith("Q:"):
                    # 落库上一个问题
                    if cur_q is not None:
                        faqs.append({"q": cur_q, "a": "\n".join(cur_a_lines).strip(), "section": section})
                    cur_q = line[2:].strip()
                    cur_a_lines = []
                    continue
                if line.startswith("A:"):
                    cur_a_lines.append(line[2:].strip())
                    continue
                # 其它行：若是答案的续行并入答案
                if cur_q is not None:
                    cur_a_lines.append(line)
        # 文件尾落库
        if cur_q is not None:
            faqs.append({"q": cur_q, "a": "\n".join(cur_a_lines).strip(), "section": section})
    except FileNotFoundError:
        logger.warning(f"[faq]FAQ 文件不存在：{path}")
        faqs = []
    except Exception as e:
        logger.error(f"[faq]解析 FAQ 失败：{str(e)[:200]}")
        faqs = []

    _faq_cache = faqs
    _faq_path_used = path
    logger.info(f"[faq]已加载 {len(faqs)} 条 FAQ 问答（{path}）")
    return faqs


def faq_lookup(question: str, top_k: int = 1) -> str:
    """
    精确命中 FAQ：
      1. 完全归一化匹配 → 直接返回
      2. 子串包含（问句互含）→ 返回
      3. 词重叠打分取最高 top_k
    入参：question - 用户问题
    返回：命中的完整 Q&A 文本；未命中返回空字符串（让 Agent 转 rag_summarize）。
    """
    question = (question or "").strip()
    if not question:
        return ""
    faqs = load_faq()
    if not faqs:
        return ""

    q_norm = _norm(question)
    # 1/2 精确 + 子串
    for f in faqs:
        fn = _norm(f["q"])
        if fn == q_norm or (len(fn) > 3 and (fn in q_norm or q_norm in fn)):
            return _format_answer(f)

    # 3 词重叠打分（简单位拆分）
    q_chars = set(q_norm)  # 字符级重叠，避免分词
    best = []
    for f in faqs:
        fn = _norm(f["q"])
        fn_chars = set(fn)
        if not fn_chars:
            continue
        overlap = len(q_chars & fn_chars)
        score = overlap / max(len(q_chars), len(fn_chars), 1)
        if score >= 0.35:  # 覆盖率阈值，低于视为无关
            best.append((score, f))
    best.sort(key=lambda x: x[0], reverse=True)

    if not best:
        return ""
    selected = [f for _, f in best[:top_k]]
    return "\n\n".join(_format_answer(f) for f in selected)


def _format_answer(f: dict) -> str:
    """把一条 FAQ 拼成返回给 Agent 的文本"""
    section = f.get("section", "")
    head = f"[FAQ]「{f['q']}」" + (f"（{section}）" if section else "")
    return f"{head}\n{f['a']}"


if __name__ == '__main__':
    print(faq_lookup("怎么下单"))
    print("---")
    print(faq_lookup("退款要多久"))
    print("--- 未命中 ---")
    print(repr(faq_lookup("今天天气怎么样")))
