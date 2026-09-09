# PDF 内嵌图片抽取工具
# 功能：从 PDF 里把"内嵌图片"抽取出来落盘，并记录每张图所属页的文本（作为检索上下文锚点）。
# 用 PyMuPDF(fitz)：page.get_text() 抽该页文本、page.get_images(full=True)+page.extract_image(xref) 取图字节。
# 被 rag/multimodal_ingest.py 调用（把含图 PDF 转成图文条目入库）。
#
# 输出：对每张图返回
#   {img_url(落盘后 /files URL), data_url(喂 embedding), mime, page_text(所属页文本), page_no}
# 图落盘到 data/uploads（该目录已被 api_service mount /files 静态托管）。

import os
import sys
import uuid
import base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger_handler import logger
from utils.path_tool import get_abs_path

# 与 api_service.UPLOAD_DIR 一致：图落盘这里即被 http://localhost:8000/files/<name> 访问
UPLOAD_DIR = get_abs_path("data/uploads")

# 每个 PDF 最多抽取图片数（防超大 PDF 拖垮入库）
MAX_IMAGES_PER_PDF = 20
# 每张图所属页上下文文本上限（喂 caption 参考，太长会稀释图文检索）
MAX_PAGE_TEXT = 1500


def _mime_for(ext: str) -> str:
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    }.get(ext.lower(), "image/png")


def extract_pdf_images(pdf_path: str) -> list[dict]:
    """从 PDF 抽取内嵌图片并落盘到 data/uploads。

    返回：list[dict]，每项含
      img_url      - 对外 /files 访问 URL（http://localhost:8000/files/<uuid>.<ext>）
      img_name     - 落盘文件名
      data_url     - data:image/...;base64,..（喂 embedding 用）
      mime         - MIME
      page_text    - 图片所在页的文本（前 MAX_PAGE_TEXT 字）
      page_no      - 页码(0-based)
    返回空表 = 无有效内嵌图或解析失败（绝不抛到上层）。
    """
    try:
        import pymupdf  # PyMuPDF 1.28+（旧 fitz 已弃用）
    except Exception:
        try:
            import fitz as pymupdf  # 兼容旧版
        except Exception as e:
            logger.error(f"[pdf_img]PyMuPDF 未安装，无法抽图：{e}")
            return []

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    out: list[dict] = []
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        logger.error(f"[pdf_img]打开 {pdf_path} 失败：{e}")
        return []

    try:
        for pno, page in enumerate(doc):
            page_text = (page.get_text() or "").strip()[:MAX_PAGE_TEXT]
            try:
                imgs = page.get_images(full=True)
            except Exception:
                imgs = []
            for img in imgs:
                if len(out) >= MAX_IMAGES_PER_PDF:
                    logger.warning(f"[pdf_img]{pdf_path} 图片超过 {MAX_IMAGES_PER_PDF}，截断")
                    break
                try:
                    xref = img[0]
                    # pymupdf 1.28+：extract_image 移到文档级 doc.extract_image(xref)
                    info = doc.extract_image(xref)
                except Exception as e:
                    logger.warning(f"[pdf_img]提取 p{pno} 图失败：{str(e)[:100]}")
                    continue
                if not info or not info.get("image"):
                    continue
                ext = (info.get("ext") or "png").lower()
                raw = info["image"]
                # 落盘 uuid 命名，避免重名/中文名
                name = uuid.uuid4().hex + "." + ext
                with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
                    f.write(raw)
                mime = _mime_for(ext)
                data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
                out.append({
                    "img_url": f"/files/{name}",
                    "img_name": name,
                    "data_url": data_url,
                    "mime": mime,
                    "page_text": page_text,
                    "page_no": pno,
                })
    finally:
        try:
            doc.close()
        except Exception:
            pass
    logger.info(f"[pdf_img]{pdf_path} 抽取 {len(out)} 张内嵌图")
    return out


if __name__ == "__main__":
    # 自测：对任意 pdf 抽图
    import sys as _s
    p = _s.argv[1] if len(_s.argv) > 1 else "data/扫地机器人100问.pdf"
    items = extract_pdf_images(get_abs_path(p))
    for it in items[:5]:
        print(it["img_url"], it["mime"], "page", it["page_no"], "| text_len", len(it["page_text"]))
    print("total:", len(items))
