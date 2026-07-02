# 日志模块
# 功能：提供统一的日志记录能力，同时输出到控制台和文件
# 被几乎所有模块调用（config_handler、prompt_loader、file_handler、vector_store、agent_tools、middleware 等）
# 核心设计：控制台只显示 INFO 及以上级别，文件记录 DEBUG 及以上级别（更详细）

import logging
from utils.path_tool import get_abs_path  # 路径工具

import os
from datetime import time, datetime

# 日志文件保存的根目录
LOG_ROOT = get_abs_path("logs")

# 确保 logs 目录存在，不存在则自动创建（exist_ok=True 表示已存在也不报错）
os.makedirs(LOG_ROOT, exist_ok=True)

# 日志格式：时间 - 日志器名 - 级别 - 文件名:行号 - 消息内容
DEFAULT_LOG_FORMAT = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)


def get_logger(
        name: str = "agent",               # 日志器名称，默认 "agent"
        console_level: int = logging.INFO, # 控制台输出的最低级别（INFO=20，只显示 INFO/WARNING/ERROR/CRITICAL）
        file_level: int = logging.DEBUG,   # 文件输出的最低级别（DEBUG=10，显示所有级别）
        log_file=None,                     # 日志文件路径，为 None 时自动生成
) -> logging.Logger:
    """
    获取或创建一个日志器
    入参：name - 日志器名称，console_level - 控制台级别，file_level - 文件级别，log_file - 文件路径
    返回：配置好的 Logger 对象
    """
    # 获取名为 name 的日志器（同名返回同一个对象）
    logger = logging.getLogger(name)
    # 设置日志器的最低级别为 DEBUG（让 Handler 自己过滤）
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 Handler（同一个日志器多次调用 get_logger 时不会重复输出）
    if logger.handlers:
        return logger

    # ---- 控制台 Handler：将日志输出到终端 ----
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)        # 控制台只显示 INFO 及以上
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)  # 应用格式
    logger.addHandler(console_handler)              # 绑定到日志器

    # ---- 文件 Handler：将日志写入文件 ----
    if not log_file:
        # 自动生成日志文件路径：logs/agent_20260604.log
        log_file = os.path.join(LOG_ROOT, f"{name}_{datetime.now().strftime('%Y%m%d')}.log")

    # 创建文件 Handler，UTF-8 编码（支持中文）
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(file_level)              # 文件记录 DEBUG 及以上（更详细）
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)  # 应用格式
    logger.addHandler(file_handler)                # 绑定到日志器

    return logger


# 模块级变量：创建一个默认日志器，其他模块直接 import logger 使用
logger = get_logger()

if __name__ == '__main__':
    # 直接运行此文件时，测试各级别日志是否正常
    logger.info("信息日志")
    logger.error("错误日志")
    logger.warning("警告日志")
    logger.debug("调试日志")
