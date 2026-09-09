# 图片理解工具（读图 / 多模态）
# 功能：给一张图片（URL 或 base64 data-url）→ 返回 AI 对图片内容的文字描述
# 被 agent/react_agent.py 注册为工具，供用户上传菜单/菜品截图等场景使用
# 模型：qwen-vl-plus（DashScope 兼容 OpenAI 接口，与主模型同 key）
# 设计：惰性创建视觉 ChatModel，避免 import 时即构造（且未配置 key 不抛错）

import os
import re
import base64
import mimetypes
from urllib.parse import urlparse
from utils.config_handler import rag_conf, get_abs_path, load_dotenv  # 读取 vision_model_name；显式确保 .env 已加载
from utils.logger_handler import logger

# 视觉模型用 os.getenv("DASHSCOPE_API_KEY")，若本模块被独立 import 可能绕过 config_handler 自动加载，这里显式补一次
load_dotenv(get_abs_path(".env"))

# 本地图片 base64 体积上限（字节）—— 过大 DashScope 会 422
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB

_vision_client = None


def _model_name() -> str:
    """视觉模型名（config/rag.yml -> vision_model_name），缺省 qwen-vl-plus"""
    try:
        return rag_conf.get("vision_model_name", "qwen-vl-plus") or "qwen-vl-plus"
    except Exception:
        return "qwen-vl-plus"


def _get_client():
    """惰性创建 ChatOpenAI 视觉客户端（复用 DASHSCOPE_API_KEY）"""
    global _vision_client
    if _vision_client is None:
        from langchain_openai import ChatOpenAI
        _vision_client = ChatOpenAI(
            model=_model_name(),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=60,
        )
    return _vision_client


_IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF8": "gif",
    b"RIFF": "webp",   # webp 以 RIFF....WEBP 开头
    b"BM": "bmp",
}


def _is_valid_image_ref(ref: str) -> bool:
    """粗校验 image_ref 是否为 http(s) URL 或 data:image base64"""
    ref = (ref or "").strip()
    if re.match(r"^https?://", ref, re.I):
        return True  # URL 格式合法即放行（真实图片内容由视觉模型/远端校验；本地可探测见 _looks_like_image_url）
    if ref.startswith("data:image/"):
        # 校验 base64 体积不超限
        try:
            b64 = ref.split(",", 1)[1] if "," in ref else ""
            if len(b64) * 3 // 4 > MAX_IMAGE_BYTES:
                return False  # 超限
            return bool(b64)
        except Exception:
            return False
    return False


# 本服务上传文件的静态目录（与 api_service.UPLOAD_DIR 一致），用于把 /files/.. 转成本地磁盘路径
_UPLOAD_DIR = get_abs_path("data/uploads")


def _is_local_files_url(url: str) -> bool:
    """判断 URL 是否指向本服务自己的 /files 静态资源（localhost/127.0.0.1 + /files/ 路径）"""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if p.hostname not in ("localhost", "127.0.0.1"):
        return False
    return p.path.startswith("/files/")


def _local_file_to_data_url(url: str) -> str | None:
    """把本服务 /files/.. 的 URL 读成本地文件，转成 data:image/...;base64,.. 供视觉模型读取。
    返回 None 表示文件不存在/非图片。"""
    try:
        name = os.path.basename(urlparse(url).path)
    except Exception:
        return None
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        return None
    path = os.path.join(_UPLOAD_DIR, name)
    if not os.path.isfile(path):
        return None
    mime = mimetypes.guess_type(name)[0] or "image/png"
    if not mime.startswith("image/"):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > MAX_IMAGE_BYTES:
            return "__TOO_LARGE__"
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    except Exception as e:
        logger.warning(f"[describe_image]读本地图失败 {name}: {str(e)[:120]}")
        return None


def _looks_like_image_url(url: str) -> bool:
    """
    对 http(s) 图片 URL 做轻量预检：先看扩展名，再看内容前几字节 magic number。
    返回 True=像图片；False=明显不是（可避免把 .txt/.html 发给视觉模型报 400）。
    """
    path = (url.split("?", 1)[0] or "").lower()
    if path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
        return True
    # 无图片扩展名 → 尝试抓前 16 字节看 magic number（失败则放行，交给模型）
    import httpx
    try:
        r = httpx.get(url, timeout=6.0, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"},)
        if r.status_code != 200:
            return False
        head = r.content[:16]
        for magic in _IMAGE_MAGIC:
            if head.startswith(magic):
                return True
        # 网页/文本明显不是图
        ctype = r.headers.get("content-type", "").lower()
        if "image/" in ctype:
            return True
        return False
    except Exception:
        return True  # 探测失败不阻断（乐观放行，靠模型兜底）


def describe_image(image_ref: str) -> str:
    """
    描述图片内容
    入参：image_ref - 图片 URL（https://...）或 data-url（data:image/png;base64,...）
    返回：图片内容的文字描述。失败/未配置 key 时返回提示文案，不抛异常。
    """
    image_ref = (image_ref or "").strip()
    if not _is_valid_image_ref(image_ref):
        return "【读图失败】请提供有效的图片链接（http/https）或 base64 图片（data:image/...）。"

    # 本服务 /files 上传图 → 直接读本地磁盘转 data-url 发给视觉模型：
    # 避免 DashScope 尝试从 http://localhost 下载（公网不可达）导致 400 Failed to download
    if image_ref.startswith("http") and _is_local_files_url(image_ref):
        local = _local_file_to_data_url(image_ref)
        if local == "__TOO_LARGE__":
            return "【读图失败】图片超过 5MB，无法读取。"
        if local is None:
            return "【读图失败】图片文件不存在或不是有效图片，可能已被清理。"
        image_ref = local

    # URL（非本地）且不像图片 → 提前拒绝，避免把 .txt/.html 发给视觉模型报 400
    if image_ref.startswith("http") and not _looks_like_image_url(image_ref):
        return "【读图失败】该链接看起来不是图片（图片应为 .png/.jpg/.gif/.webp 等），请提供有效的图片链接。"

    if not os.getenv("DASHSCOPE_API_KEY"):
        return "【读图未启用】未配置 DASHSCOPE_API_KEY，无法进行图片理解。"

    try:
        from langchain_core.messages import HumanMessage
        client = _get_client()
        resp = client.invoke([
            HumanMessage(content=[
                {"type": "text", "text": "请详细描述这张图片的内容。如果是菜单/菜品/单据，请尽量完整识别其中的文字信息。"},
                {"type": "image_url", "image_url": {"url": image_ref}},
            ])
        ])
        content = str(getattr(resp, "content", "")).strip()
        logger.info(f"[describe_image]读图完成（{len(content)} 字）")
        return content if content else "【读图】模型未返回有效描述。"
    except Exception as e:
        logger.error(f"[describe_image]读图失败：{str(e)[:200]}")
        return f"【读图失败】{str(e)[:120]}"


if __name__ == '__main__':
    # 测试：可用任意公开图片 URL 替换
    print(describe_image("https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"))
