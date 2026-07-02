# 路径工具模块
# 功能：为整个项目提供统一的绝对路径计算能力
# 被 config_handler.py、prompt_loader.py、vector_store.py 等几乎所有需要读文件的模块调用
# 核心思路：从当前文件位置反推项目根目录，再拼接相对路径得到绝对路径

import os


def get_project_root() -> str:
    """
    获取项目根目录的绝对路径
    原理：当前文件是 utils/path_tool.py，往上跳一级就是项目根目录
    返回：项目根目录的绝对路径字符串
    """
    # __file__ 是当前文件（path_tool.py）的绝对路径
    # 例如：C:/Users/26716/PycharmProjects/LangChain-ReAct-Agent/utils/path_tool.py
    current_file = os.path.abspath(__file__)

    # os.path.dirname() 获取文件所在的文件夹
    # 结果：C:/Users/.../LangChain-ReAct-Agent/utils
    current_dir = os.path.dirname(current_file)

    # 再往上跳一级，得到项目根目录
    # 结果：C:/Users/.../LangChain-ReAct-Agent
    project_root = os.path.dirname(current_dir)

    return project_root


def get_abs_path(relative_path: str) -> str:
    """
    将项目内的相对路径转为绝对路径
    入参：relative_path - 相对于项目根目录的路径，如 "config/rag.yml"
    返回：完整的绝对路径，如 "C:/Users/.../config/rag.yml"
    """
    # 先获取项目根目录
    project_root = get_project_root()
    # os.path.join() 将根目录和相对路径拼接成完整路径
    return os.path.join(project_root, relative_path)


if __name__ == '__main__':
    # 直接运行此文件时，测试路径计算是否正确
    print(get_abs_path("config/config.txt"))
