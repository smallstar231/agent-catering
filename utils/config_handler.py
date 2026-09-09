# 配置加载模块
# 功能：读取 config/ 目录下的所有 YAML 配置文件，解析为 Python 字典
# 被 model/factory.py、rag/vector_store.py、agent/tools/agent_tools.py、utils/prompt_loader.py 等调用
# 核心设计：模块级变量（rag_conf 等）在 import 时一次性加载，全局共享，不会重复读文件

import yaml
from dotenv import load_dotenv  # 从 .env 加载环境变量（DASHSCOPE_API_KEY / TAVILY_API_KEY 等）
from utils.path_tool import get_abs_path

# 在“任何需要读取环境变量的模块”之前先加载 .env：
# 本模块被全链路几乎所有模块 import（model/factory、rag/vector_store、agent/tools 等），
# 在这里最先执行 load_dotenv() 即可保证所有模块级单例拿到的 os.getenv 都来自 .env。
# 显式指向项目根目录 .env（不依赖启动时 cwd），文件不存在则静默跳过。
load_dotenv(get_abs_path(".env"))


def load_rag_config(config_path: str = get_abs_path("config/rag.yml"), encoding: str = "utf-8"):
    """
    加载 RAG 和模型配置（config/rag.yml）
    默认参数：config_path 在函数定义时就计算好了（get_abs_path 在 import 时执行）
    返回：字典，如 {"chat_model_name": "qwen3-max", "embedding_model_name": "text-embedding-v4"}
    """
    with open(config_path, "r", encoding=encoding) as f:
        # yaml.load() 将 YAML 文本解析为 Python 字典
        # Loader=yaml.FullLoader 是安全的解析器，防止执行任意代码
        return yaml.load(f, Loader=yaml.FullLoader)


def load_chroma_config(config_path: str = get_abs_path("config/chroma.yml"), encoding: str = "utf-8"):
    """
    加载向量数据库配置（config/chroma.yml）
    返回：字典，包含 collection_name、persist_directory、k、chunk_size 等
    """
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_prompts_config(config_path: str = get_abs_path("config/prompts.yml"), encoding: str = "utf-8"):
    """
    加载提示词路径配置（config/prompts.yml）
    返回：字典，包含 main_prompt_path、rag_summarize_prompt_path、report_prompt_path
    """
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_agent_config(config_path: str = get_abs_path("config/agent.yml"), encoding: str = "utf-8"):
    """
    加载 Agent 配置（config/agent.yml）
    返回：字典，包含 external_data_path 等
    """
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def load_conv_config(config_path: str = get_abs_path("config/conv.yml"), encoding: str = "utf-8"):
    """
    加载会话历史压缩配置（config/conv.yml）
    返回：字典，包含 history_char_budget / protected_rounds 等
    """
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


# ---- 模块级变量：import 时自动执行，全局共享 ----
# 这四行在 "import config_handler" 时就执行了，之后所有模块拿到的是同一份字典对象
# 相当于全局单例：读一次文件，到处复用
rag_conf = load_rag_config()          # RAG 和模型配置
chroma_conf = load_chroma_config()    # 向量数据库配置
agent_conf = load_agent_config()      # Agent 配置
prompts_conf = load_prompts_config()  # 提示词路径配置
conv_conf = load_conv_config()        # 会话历史压缩配置

if __name__ == '__main__':
    # 直接运行此文件时，测试配置加载是否正常
    print(agent_conf["chat_model_name"])
