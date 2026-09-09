# 上传文件解析工具（读 txt / pdf）
# 功能：给定用户上传文件生成的引用（本服务 /files 静态 URL、或[文件:URL|名称]标记、或外部 https 文件），
#       下载/读取并解析成纯文本，供 Agent 阅读内容后回答用户问题。
# 背景：与 M7「传图」同思路——前端上传文件 → 消息注入 [文件:URL|文件名] 标记 → Agent 见标记自动调本工具解析。
# 设计：
#   - 本服务自己的文件：URL 形如 http://localhost:8000/files/<uuid>.ext，直接按磁盘路径读取（不走网络、不触发 SSRF）；
#   - 外部 http(s) 文件：复用 page_reader 的 SSRF 防护（拒绝内网/环回等），经 httpx 下载后解析；
#   - 参数容错：传入完整标记 [文件:链接|名] 或裸链接都行，内部自动提取链接。
#   - txt 用编码容错解码(utf-8→gbk)，pdf 用 pypdf 抽取文字；一律有长度上限与截断提示，绝不抛异常。

import os
import re
from io import BytesIO
from urllib.parse import urlparse

import httpx
from utils.path_tool import get_abs_path
from utils.logger_handler import logger

# 单文件大小上限（上传接口已按此校验，下载外部文件时同样按字节数流式截断）
MAX_FILE_BYTES = 10 * 1024 * 1024      # 10MB
# 解析后文本返回给 LLM 的最大字符数（超出截断）
MAX_TEXT_CHARS = 12000
# 本服务文件挂载的静态目录（对应 api_service app.mount("/files", ...)）
UPLOAD_DIR = get_abs_path("data/uploads")
# 本服务文件 URL 前缀判断（dev 固定 localhost:8000）
_LOCAL_FILES_PREFIXES = ("/files/",)
_HTTP_TIMEOUT = 20.0


def _extract_url(ref: str) -> str:
    """从入参中容错提取文件链接：
    接受 裸链接(http/https) 或 [文件:<链接>|<文件名>] 标记，取到真正的 URL。
    解析失败返回原串（交给后续校验兜底）。"""
    s = (ref or "").strip()
    # 去尾部多余的 "]"
    if s.endswith("]"):
        s = s[:-1]
    # 形如 "[文件:URL" 或 "文件:URL" → 取冒号后
    m = re.search(r"\[?文件[:：]\s*([^\s|]+)", s)
    if m:
        return m.group(1).strip().rstrip("]")
    # 形如 "URL|文件名" → 取 '|' 前
    if "|" in s:
        return s.split("|", 1)[0].strip()
    return s


def _is_local_url(url: str) -> bool:
    """判断是否指向本服务自己的 /files 静态资源（localhost/127.0.0.1 + /files/ 路径）"""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if p.hostname not in ("localhost", "127.0.0.1"):
        return False
    return any(p.path.startswith(prefix) for prefix in _LOCAL_FILES_PREFIXES)


def _read_local_file(url: str) -> bytes | None:
    """从磁盘读取本服务 data/uploads 下的文件（URL → data/uploads/<basename>）。
    返回 None 表示不存在或文件名非法。"""
    try:
        name = os.path.basename(urlparse(url).path)
    except Exception:
        return None
    # 防穿越：只允许纯文件名
    if name in ("", ".", "..") or "/" in name or "\\" in name or not name:
        return None
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def _fetch_external(url: str) -> bytes | str:
    """下载外部 http(s) 文件（先经 SSRF 防护）。返回 bytes 或错误文案 str。"""
    from agent.tools.page_reader import _guard_url  # 复用 SSRF 防护（拒绝内网/环回/保留地址）
    blocked = _guard_url(url)
    if blocked:
        return f"【文件读取被拒】{blocked}"
    try:
        with httpx.stream("GET", url, timeout=_HTTP_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"}) as r:
            if r.status_code != 200:
                return f"【文件下载失败】HTTP {r.status_code}"
            buf = bytearray()
            for chunk in r.iter_bytes(chunk_size=64 * 1024):
                buf.extend(chunk)
                if len(buf) > MAX_FILE_BYTES:
                    return "【文件过大】超过 10MB 上限，无法解析。"
            return bytes(buf)
    except Exception as e:
        logger.debug(f"[read_file]下载失败 {url}: {str(e)[:120]}")
        return f"【文件下载失败】{str(e)[:120]}"


# ---- 文本解码：utf-8 → gbk 容错 ----
def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---- PDF 解析：pypdf 抽文字（惰性 import） ----
def _parse_pdf(data: bytes, name: str) -> str:
    try:
        from pypdf import PdfReader
    except Exception as e:
        return f"【PDF 解析不可用】缺少 pypdf 库：{str(e)[:100]}"
    try:
        reader = PdfReader(BytesIO(data))
        pages = len(reader.pages)
        texts: list[str] = []
        total = 0
        for i, page in enumerate(reader.pages):
            try:
                t = (page.extract_text() or "").strip()
            except Exception:
                t = ""
            if t:
                texts.append(f"--- 第{i + 1}页 ---\n{t}")
                total += len(t)
                if total >= MAX_TEXT_CHARS:
                    texts.append("...(内容过长已截断)")
                    break
        body = "\n".join(texts).strip()
        if not body:
            return f"【PDF 未提取到文字】{name} 可能是扫描件/图片型 PDF，无法读取文字内容。"
        return f"文件名：{name}（PDF，共 {pages} 页）\n内容如下：\n{body}"
    except Exception as e:
        logger.error(f"[read_file]解析 pdf 失败 {name}: {str(e)[:200]}")
        return f"【PDF 解析失败】{str(e)[:150]}"


def read_file(ref: str) -> str:
    """
    读取一个上传的 txt/pdf 文件并返回解析后的纯文本内容。
    入参：ref - 文件链接(https://...) 或文件标记([文件:链接|文件名])。
    返回：文件文字内容（pdf 逐页抽取，可能截断）。失败返回原因文案，绝不抛异常。
    """
    url = _extract_url(ref)
    if not re.match(r"^https?://", url, re.I):
        return "【文件读取失败】入参需为文件链接（http/https）或 [文件:链接|文件名] 标记。"

    # 从 URL 取文件名与扩展名（决定解析方式）
    path_lower = (urlparse(url).path or "").lower()
    name = os.path.basename(path_lower) or "file"

    if _is_local_url(url):
        data = _read_local_file(url)
        if data is None:
            return f"【文件读取失败】文件不存在或已被清理：{name}"
    else:
        got = _fetch_external(url)
        if isinstance(got, str):
            return got  # 错误文案
        data = got

    if len(data) > MAX_FILE_BYTES:
        return "【文件过大】超过 10MB 上限，无法解析。"

    # 按扩展名/内容选择解析
    if path_lower.endswith(".pdf"):
        return _parse_pdf(data, name)
    # 其余（.txt / 未知）一律按纯文本尝试
    if path_lower.endswith(".txt") or _looks_binary(data) is False:
        text = _decode_text(data)
    else:
        # 未知扩展名但看着像二进制 → 给出提示，避免乱码进上下文
        return f"【不支持的文件类型】仅支持 txt / pdf，当前文件为：{name}"

    if not text.strip():
        return f"【文件为空】{name} 没有任何可读取的文字内容。"
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n...(内容过长已截断)"
    logger.info(f"[read_file]成功读取 {name}（{len(text)} 字符）")
    return f"文件名：{name}\n内容如下：\n{text}"


def _looks_binary(data: bytes) -> bool:
    """简单启发式：前 1024 字节含 NUL/高比例控制字符则视为二进制"""
    head = data[:1024]
    if not head:
        return False
    nul = head.count(b"\x00")
    if nul > 0:
        return True
    ctrl = sum(1 for b in head if b < 9 or (13 < b < 32))
    return ctrl / len(head) > 0.3


if __name__ == '__main__':
    # 自测：需要一个本服务上传的 txt 路径
    print(read_file("[文件:http://localhost:8000/files/demo.txt|演示.txt]"))
