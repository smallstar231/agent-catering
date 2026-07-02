# 向量存储服务模块
# 功能：管理 Chroma 向量库——初始化、文档加载、分片、存储、检索
# 被 rag/rag_service.py 调用（获取检索器）
# 被首次运行时的知识库初始化脚本调用（加载文档）

from langchain_chroma import Chroma                           # LangChain 的 Chroma 向量库封装
from langchain_core.documents import Document                 # 文档对象（page_content + metadata）
from utils.config_handler import chroma_conf                  # 向量库配置

from model.factory import embed_model                         # Embedding 模型（文本转向量）

from langchain_text_splitters import RecursiveCharacterTextSplitter  # 文档分片器
from utils.path_tool import get_abs_path                      # 路径工具
from utils.file_handler import pdf_loader, txt_loader, listdir_with_allowed_type, get_file_md5_hex  # 文件工具
from utils.logger_handler import logger                       # 日志记录器

import os


class VectorStoreService:
    """
    向量存储服务
    职责：管理 Chroma 向量库的生命周期——初始化、文档加载、分片、存储、检索
    支持多场景隔离：robot（扫地机器人）| sky（苍穹外卖），不同场景使用不同集合
    """

    def __init__(self, scene: str = "robot"):
        """
        初始化向量库和分片器
        入参：scene - 场景名称，"robot"（默认，扫地机器人）或 "sky"（苍穹外卖）
        """
        # 根据场景选择 Chroma 集合配置
        if scene == "sky":
            _collection = chroma_conf["collection_name_sky"]
            _persist_dir = chroma_conf["persist_directory_sky"]
        else:
            _collection = chroma_conf["collection_name"]
            _persist_dir = chroma_conf["persist_directory"]

        self.scene = scene

        # 初始化 Chroma 向量库
        # collection_name：集合名称（类似数据库的表名）
        # embedding_function：Embedding 模型，用于将文本转为向量
        # persist_directory：数据持久化目录，重启后数据不丢失
        self.vector_store = Chroma(
            collection_name=_collection,
            embedding_function=embed_model,
            persist_directory=_persist_dir,
        )

        # 初始化文档分片器
        # chunk_size：每个切片最大 200 字符
        # chunk_overlap：相邻切片重叠 20 字符（保证上下文连贯）
        # separators：分割符优先级（段落 → 句号 → 问号 → 空格 → 任意位置）
        # length_function：用 len() 计算文本长度
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )

    def get_retriever(self):
        """
        获取检索器：用于从向量库中检索与查询最相关的文档
        返回：Chroma Retriever 对象，可以调用 .invoke(query) 检索
        search_kwargs={"k": 3} 表示返回前 3 条最相关的结果
        """
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf["k"]})

    def _get_md5_path(self) -> str:
        """根据场景返回对应的 MD5 记录文件路径"""
        if self.scene == "sky":
            return get_abs_path(chroma_conf["md5_hex_store_sky"])
        return get_abs_path(chroma_conf["md5_hex_store"])

    def _is_scene_file(self, filename: str) -> bool:
        """判断文件是否属于当前场景的知识库"""
        if self.scene == "sky":
            # 苍穹外卖场景：只加载以"苍穹外卖"开头的文件
            return filename.startswith("苍穹外卖")
        else:
            # 机器人场景：排除以"苍穹外卖"开头的文件
            return not filename.startswith("苍穹外卖")

    def load_document(self):
        """
        从 data/ 目录加载知识库文档到向量库
        流程：扫描文件 → 计算 MD5 去重 → 加载文档 → 分片 → 转向量 → 存入 Chroma
        """

        def check_md5_hex(md5_for_check: str):
            """
            检查 MD5 是否已存在（文件是否已处理过）
            入参：md5_for_check - 文件的 MD5 哈希值
            返回：True = 已处理过（跳过），False = 未处理过（需要加载）
            """
            md5_file = self._get_md5_path()

            # 如果 MD5 记录文件不存在，创建一个空文件
            if not os.path.exists(md5_file):
                open(md5_file, "w", encoding="utf-8").close()
                return False  # 文件是新的，肯定没处理过

            # 逐行读取 MD5 记录，检查是否匹配
            with open(md5_file, "r", encoding="utf-8") as f:
                for line in f.readlines():
                    line = line.strip()
                    if line == md5_for_check:
                        return True   # 找到了，已处理过

                return False  # 遍历完没找到，未处理过

        def save_md5_hex(md5_for_check: str):
            """
            将已读取文件内容且不在md5.txt的文件（的 MD5） 追加写入记录文件
            入参：md5_for_check - 文件的 MD5 哈希值
            """
            with open(self._get_md5_path(), "a", encoding="utf-8") as f:
                f.write(md5_for_check + "\n")

        def get_file_documents(read_path: str):
            """
            根据文件后缀选择对应的加载器
            入参：read_path - 文件路径
            返回：list[Document]，每个 Document 包含 page_content 和 metadata
            """
            if read_path.endswith("txt"):
                return txt_loader(read_path)
            if read_path.endswith("pdf"):
                return pdf_loader(read_path)
            return []

        # Step 1：扫描 data/ 目录，获取所有 .txt 和 .pdf 文件的完整路径
        allowed_files_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )

        # Step 1.5：根据场景过滤文件（机器人场景排除苍穹外卖文档，苍穹外卖场景只加载苍穹外卖文档）
        allowed_files_path = [
            f for f in allowed_files_path
            if self._is_scene_file(os.path.basename(f))
        ]

        # Step 2：逐个处理文件
        for path in allowed_files_path:
            # 计算文件的 MD5 哈希值
            md5_hex = get_file_md5_hex(path)

            # 检查是否已处理过（MD5 去重）
            if check_md5_hex(md5_hex):
                logger.info(f"[加载知识库]{path}内容已经存在知识库内，跳过")
                continue  # 跳过这个文件，处理下一个

            try:
                # 加载文件内容为 Document 列表
                documents: list[Document] = get_file_documents(path)

                # 安全检查：文件可能是空的
                if not documents:
                    logger.warning(f"[加载知识库]{path}内没有有效文本内容，跳过")
                    continue

                # 将文档分片（每片 200 字符，重叠 20 字符）
                split_document: list[Document] = self.spliter.split_documents(documents)

                # 安全检查：分片后可能是空的
                if not split_document:
                    logger.warning(f"[加载知识库]{path}分片后没有有效文本内容，跳过")
                    continue

                # 将分片后的文档存入 Chroma 向量库
                # Chroma 会自动调用 embed_model 将文本转为向量
                self.vector_store.add_documents(split_document)

                # 记录 MD5，下次运行时跳过这个文件
                save_md5_hex(md5_hex)

                logger.info(f"[加载知识库]{path} 内容加载成功")
            except Exception as e:
                # exc_info=True 记录详细的报错堆栈
                logger.error(f"[加载知识库]{path}加载失败：{str(e)}", exc_info=True)
                continue


if __name__ == '__main__':
    # 直接运行此文件时，测试知识库加载和检索
    vs = VectorStoreService()

    # 加载文档到向量库
    vs.load_document()

    # 测试检索
    retriever = vs.get_retriever()

    res = retriever.invoke("迷路")
    for r in res:
        print(r.page_content)
        print("-" * 20)
