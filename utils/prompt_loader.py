# 从配置中获取提示词文件路径，读取并返回提示词文本内容
# 被 agent/react_agent.py 和 rag/rag_service.py 调用

from utils.config_handler import prompts_conf  # 导入提示词配置（包含各提示词文件的路径）
from utils.path_tool import get_abs_path       # 将相对路径转为绝对路径的工具函数
from utils.logger_handler import logger        # 日志记录器

def load_system_prompts():
    """
    加载普通问答场景的系统提示词（main_prompt.txt）
    返回：提示词的完整文本字符串
    """
    try:
        # 从配置中读取 main_prompt_path 对应的路径，转为绝对路径
        system_prompt_path = get_abs_path(prompts_conf["main_prompt_path"])
    except KeyError as e:
        # 如果配置中没有 main_prompt_path 这个键，记录错误并抛出
        logger.error(f"[load_system_prompts]在yaml配置项中没有main_prompt_path配置项")
        raise e

    try:
        # 打开文件，读取全部内容并返回字符串
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        # 文件不存在或读取失败时，记录错误并抛出
        logger.error(f"[load_system_prompts]解析系统提示词出错，{str(e)}")
        raise e


def load_rag_prompts():
    """
    加载 RAG 总结场景的提示词（rag_summarize.txt）
    返回：提示词的完整文本字符串，包含 {input} 和 {context} 两个模板变量
    """
    try:
        # 从配置中读取 rag_summarize_prompt_path 对应的路径，转为绝对路径
        rag_prompt_path = get_abs_path(prompts_conf["rag_summarize_prompt_path"])
    except KeyError as e:
        logger.error(f"[load_rag_prompts]在yaml配置项中没有rag_summarize_prompt_path配置项")
        raise e

    try:
        return open(rag_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[load_rag_prompts]解析RAG提示词出错，{str(e)}")
        raise e


def load_report_prompts():
    """
    加载报告生成场景的系统提示词（report_prompt.txt）
    返回：提示词的完整文本字符串
    """
    try:
        # 从配置中读取 report_prompt_path 对应的路径，转为绝对路径
        report_prompt_path = get_abs_path(prompts_conf["report_prompt_path"])
    except KeyError as e:
        logger.error(f"[load_report_prompts]在yaml配置项中没有report_prompt_path配置项")
        raise e

    try:
        return open(report_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[load_report_prompts]解析报告生成提示词出错，{str(e)}")
        raise e


# ---- 苍穹外卖场景加载函数（新增）----

def load_system_prompts_sky():
    """
    加载苍穹外卖场景的系统提示词（main_prompt_sky.txt）
    返回：提示词的完整文本字符串
    """
    try:
        system_prompt_path = get_abs_path(prompts_conf["main_prompt_sky_path"])
    except KeyError as e:
        logger.error(f"[load_system_prompts_sky]在yaml配置项中没有main_prompt_sky_path配置项")
        raise e

    try:
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[load_system_prompts_sky]解析苍穹外卖系统提示词出错，{str(e)}")
        raise e


def load_rag_prompts_sky():
    """
    加载苍穹外卖 RAG 总结场景的提示词（rag_summarize_sky.txt）
    返回：提示词的完整文本字符串，包含 {input} 和 {context} 两个模板变量
    """
    try:
        rag_prompt_path = get_abs_path(prompts_conf["rag_summarize_sky_path"])
    except KeyError as e:
        logger.error(f"[load_rag_prompts_sky]在yaml配置项中没有rag_summarize_sky_path配置项")
        raise e

    try:
        return open(rag_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[load_rag_prompts_sky]解析苍穹外卖RAG提示词出错，{str(e)}")
        raise e


def load_report_prompts_sky():
    """
    加载苍穹外卖报告生成场景的系统提示词（report_prompt_sky.txt）
    返回：提示词的完整文本字符串
    """
    try:
        report_prompt_path = get_abs_path(prompts_conf["report_prompt_sky_path"])
    except KeyError as e:
        logger.error(f"[load_report_prompts_sky]在yaml配置项中没有report_prompt_sky_path配置项")
        raise e

    try:
        return open(report_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[load_report_prompts_sky]解析苍穹外卖报告提示词出错，{str(e)}")
        raise e


if __name__ == '__main__':
    # 直接运行此文件时，测试加载报告提示词
    print(load_report_prompts())
