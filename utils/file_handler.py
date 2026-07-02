# 文件处理工具模块
# 功能：提供文件 MD5 计算、文件列表过滤、PDF/TXT 文档加载、会话存档读写
# 被 rag/vector_store.py 调用，用于加载知识库文档和文件去重
# 会话存档功能被 app.py 调用，用于保存和查看历史对话

import os, hashlib, json, datetime
from utils.logger_handler import logger  # 日志记录器
from utils.path_tool import get_abs_path  # 相对路径转绝对路径

from langchain_core.documents import Document  # LangChain 文档对象（包含 page_content 和 metadata）
from langchain_community.document_loaders import PyPDFLoader, TextLoader  # PDF 和 TXT 文件加载器


def get_file_md5_hex(filepath: str):
    """
    计算文件的 MD5 哈希值（十六进制字符串）
    用途：判断文件是否已经被处理过，避免重复加载到向量库
    入参：filepath - 文件的绝对路径
    返回：MD5 十六进制字符串，如 "d41d8cd98f00b204e9800998ecf8427e"
    """
    # 安全检查：文件是否存在
    if not os.path.exists(filepath):
        logger.error(f"[MD5计算]文件{filepath}不存在")
        return
    # 安全检查：路径是否是文件（不是文件夹）
    if not os.path.isfile(filepath):
        logger.error(f"[MD5计算]路径{filepath}不是文件")
        return

    # 创建 MD5 哈希对象
    md5_obj = hashlib.md5()
    # 分片读取，每次 4KB，避免大文件一次性读入内存爆掉
    chunk_size = 4096
    try:
        # 必须用 "rb" 二进制模式读取，MD5 是对字节计算的
        with open(filepath, "rb") as f:
            # 海象运算符 := 在 while 条件中赋值，chunk 为空时循环结束
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)  # 将每片数据喂给哈希对象

        # 获取最终的十六进制哈希字符串
        md5_hex = md5_obj.hexdigest()
        return md5_hex
    except Exception as e:
        logger.error(f"计算文件{filepath}md5失败，{str(e)}")
        return None


def listdir_with_allowed_type(path: str, allowed_types: tuple[str]):
    """
    列出文件夹中指定类型的文件，返回完整路径列表
    用途：从 data/ 目录中筛选出 .txt 和 .pdf 文件
    入参：path - 文件夹路径，allowed_types - 允许的文件后缀，如 (".txt", ".pdf")
    返回：包含完整路径的元组，如 ("C:/.../data/故障排除.txt", "C:/.../data/选购指南.txt")
    """
    files = []
    # 安全检查：路径是否是文件夹
    if not os.path.isdir(path):
        logger.error(f"[lisdir_with_allowed_type]{path}不是文件夹")
        return allowed_types

    # 遍历文件夹中的所有文件
    for f in os.listdir(path):
        # 检查文件后缀是否在允许列表中
        if f.endswith(allowed_types):
            # 拼接完整路径并加入列表
            files.append(os.path.join(path, f))
    return tuple(files)


def pdf_loader(filepath: str, passwd=None) -> list[Document]:
    """
    加载 PDF 文件，返回 LangChain Document 对象列表
    入参：filepath - PDF 文件路径，passwd - PDF 密码（可选）
    返回：list[Document]，每个 Document 包含 page_content（文本内容）和 metadata（来源等元数据）
    """
    return PyPDFLoader(filepath, passwd).load()


def txt_loader(filepath: str) -> list[Document]:
    """
    加载 TXT 文件，返回 LangChain Document 对象列表
    入参：filepath - TXT 文件路径
    返回：list[Document]，每个 Document 包含 page_content 和 metadata
    """
    return TextLoader(filepath, encoding="utf-8").load()


def save_session_to_disk(messages: list, round_count: int, session_id: str | None = None, save_dir: str = "data/sessions") -> tuple:
    """
    保存或更新会话存档到 JSON 文件
    入参：
        messages - 对话消息列表（每条含 role 和 content）
        round_count - 对话轮数
        session_id - 会话 ID，传值时覆盖更新已有文件，None 时创建新文件
        save_dir - 存档目录的相对路径
    返回：(filepath, session_id) 元组，失败返回 (None, None)
    """
    if not messages:
        return None, None

    abs_save_dir = get_abs_path(save_dir)
    os.makedirs(abs_save_dir, exist_ok=True)

    now = datetime.datetime.now()

    if session_id:
        # ---- 更新已有会话：保留原始创建时间 ----
        filepath = os.path.join(abs_save_dir, f"{session_id}.json")
        created_at = ""
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                created_at = old_data.get("created_at", "")
            except Exception:
                pass
        if not created_at:
            created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # ---- 全新会话：生成新 ID ----
        session_id = now.strftime("%Y-%m-%d_%H-%M-%S")
        created_at = now.strftime("%Y-%m-%d %H:%M:%S")
        filepath = os.path.join(abs_save_dir, f"{session_id}.json")

    # 取第一条用户消息作为标题（截取前 30 字）
    title = ""
    for msg in messages:
        if msg["role"] == "user":
            title = msg["content"][:30] + ("..." if len(msg["content"]) > 30 else "")
            break
    if not title:
        title = session_id

    # 构造存档数据
    session_data = {
        "id": session_id,
        "title": title,
        "created_at": created_at,
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "round_count": round_count,
        "messages": messages,
    }

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[save_session]会话已保存：{filepath}")
        return filepath, session_id
    except Exception as e:
        logger.error(f"[save_session]保存失败：{str(e)}")
        return None, None


def load_saved_sessions(save_dir: str = "data/sessions") -> list[dict]:
    """
    从磁盘读取所有存档的会话列表
    入参：save_dir - 存档目录的相对路径
    返回：按创建时间降序排列的会话元数据列表（不含消息内容）
    """
    abs_save_dir = get_abs_path(save_dir)
    if not os.path.isdir(abs_save_dir):
        return []

    sessions = []
    try:
        for filename in sorted(os.listdir(abs_save_dir), reverse=True):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(abs_save_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 只保留元数据，不加载完整消息（节省内存）
                sessions.append({
                    "id": data.get("id", filename[:-5]),
                    "title": data.get("title", "未知会话"),
                    "created_at": data.get("created_at", "未知时间"),
                    "updated_at": data.get("updated_at", data.get("created_at", "未知时间")),
                    "round_count": data.get("round_count", 0),
                    "filepath": filepath,
                })
            except Exception as e:
                logger.error(f"[load_sessions]读取{filename}失败：{str(e)}")
                continue
        return sessions
    except Exception as e:
        logger.error(f"[load_sessions]扫描存档目录失败：{str(e)}")
        return []


def load_session_messages(filepath: str) -> list | None:
    """
    读取某个存档文件的完整消息内容
    入参：filepath - 存档文件的绝对路径
    返回：消息列表，失败返回 None
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", [])
    except Exception as e:
        logger.error(f"[load_session_messages]读取{filepath}失败：{str(e)}")
        return None
