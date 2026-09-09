# 评估打分器模块
# 功能：对 Agent 的回答进行质量打分，支持两种指标：
#   - exact_match：关键词命中率（reference 中的关键词是否出现在回答里）
#   - llm_judge：让 LLM 当裁判，判断回答是否准确覆盖了参考答案要点
# 被 run_eval.py 使用。纯函数 + 独立 LLM 调用，不干扰主 Agent。

import re
import os
from utils.logger_handler import logger


# ---------- 关键词提取 ----------
# 去掉停用词后的"要点词"，用于 exact_match 粗评
_STOPWORDS = set("的了是在有和与就不人都一个上也很到说要去会能你这那来着吧吗呢啊".split())

def _key_terms(text: str) -> set:
    """从文本提取关键词（中文：去停用词后取字或词；这里用简单字符 bigram 与排除停用字）"""
    text = re.sub(r"[^一-龥A-Za-z0-9]+", "", text or "")
    terms = set()
    # 中文取 2-gram（能较好保留"配送时间""申请退款"这类词）
    for i in range(len(text) - 1):
        bi = text[i:i+2]
        if all(ch not in _STOPWORDS for ch in bi):
            terms.add(bi)
    # 英文/数字整体
    for en in re.findall(r"[A-Za-z0-9]{2,}", text):
        terms.add(en.lower())
    return terms


def exact_match_score(answer: str, reference: str) -> float:
    """
    关键词命中率：reference 的要点词有多少比例出现在 answer 里。
    返回 0~1。reference 为空返回 0（无法评判）。
    """
    answer = answer or ""
    if not reference:
        return 0.0
    ref_terms = _key_terms(reference)
    if not ref_terms:
        return 0.0
    ans_terms = _key_terms(answer)
    if not ans_terms:
        return 0.0
    hit = len(ref_terms & ans_terms)
    return hit / len(ref_terms)


# ---------- LLM Judge ----------
_JUDGE_PROMPT = """你是问答质量评审员。请判断"助手回答"是否准确、完整地覆盖了"参考答案"中的核心信息。

<参考（标准答案核心）>
{reference}

<助手回答>
{answer}

<用户问题>
{question}

评分规则：
- 若助手回答准确覆盖了参考答案的核心要点（不要求逐字，意思对即可），判 PASS
- 若回答错误、明显缺失关键信息、或答非所问，判 FAIL
- 若无法判断，判 UNSURE

只输出一个词：PASS / FAIL / UNSURE"""


def llm_judge_score(question: str, answer: str, reference: str) -> str:
    """
    用 LLM 判断回答质量。
    返回 'PASS' / 'FAIL' / 'UNSURE'（LLM 调用失败返回 'UNSURE'）。
    """
    if not reference or not answer:
        return "UNSURE"
    try:
        from model.factory import chat_model
        from langchain_core.prompts import PromptTemplate
        from langchain_core.output_parsers import StrOutputParser
        chain = PromptTemplate.from_template(_JUDGE_PROMPT) | chat_model | StrOutputParser()
        verdict = chain.invoke({
            "reference": reference,
            "answer": answer[:800],
            "question": question,
        }).strip().upper()
        verdict = re.sub(r"[^A-Z]", "", verdict)
        if "PASS" in verdict:
            return "PASS"
        if "FAIL" in verdict:
            return "FAIL"
        return "UNSURE"
    except Exception as e:
        logger.warning(f"[eval]LLM judge 调用失败：{str(e)[:120]}，判 UNSURE")
        return "UNSURE"


if __name__ == '__main__':
    # 简单自测
    a = "一般配送时间为30-45分钟，具体视距离天气而定。"
    r = "配送时间一般30-45分钟"
    print("exact_match:", round(exact_match_score(a, r), 2))
    print("judge:", llm_judge_score("配送要多久", a, r))
