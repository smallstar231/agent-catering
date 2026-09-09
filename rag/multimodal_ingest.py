# 多模态图文入库脚本（手动运行）
# 功能：把"独立图片 + PDF 内嵌图"入库到多模态图文向量集合（qwen3-vl-embedding 2560 维）。
# 每个源文件按 md5 去重（md5_mm.txt / md5_sky_mm.txt）；--rebuild 时清空集合重扫。
# 运行：  python -m rag.multimodal_ingest --scene sky            # 增量
#         python -m rag.multimodal_ingest --scene robot --rebuild # 清空重建
#
# 处理流程(每张图)：
#   图片字节 → 落盘 data/uploads 得 /files URL(供展示) → 调 caption(视觉模型,≤300字)
#            → embed_media(caption, image data-url) 融合向量 → 写入多模态集合
#   caption 失败给空串兜底（仍能向量化，只是检索锚点弱）；单图失败不影响其它。

import os
import sys
import argparse
import hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path
from utils.file_handler import listdir_with_allowed_type, get_file_md5_hex
from utils.logger_handler import logger

from rag.multimodal_store import MultimodalVectorStore
from rag.multimodal_embedding import MultimodalEmbeddingError


def _md5_path(scene: str) -> str:
    key = "md5_hex_store_mm_sky" if scene == "sky" else "md5_hex_store_mm"
    return get_abs_path(chroma_conf[key])


def _check_md5(md5_file: str, digest: str) -> bool:
    if not os.path.exists(md5_file):
        return False
    try:
        with open(md5_file, "r", encoding="utf-8") as f:
            return digest in {ln.strip() for ln in f}
    except Exception:
        return False


def _save_md5(md5_file: str, digest: str) -> None:
    try:
        with open(md5_file, "a", encoding="utf-8") as f:
            f.write(digest + "\n")
    except Exception as e:
        logger.warning(f"[mm_ingest]写 md5 失败：{e}")


def _is_scene_file(scene: str, filename: str) -> bool:
    """与 vector_store._is_scene_file 一致：sky 只收"苍穹外卖"开头，robot 反之。"""
    if scene == "sky":
        return filename.startswith("苍穹外卖")
    return not filename.startswith("苍穹外卖")


def _caption_image(image_ref: str) -> str:
    """给一张图生成一句话描述（≤300字）。复用 vision._get_client() 的视觉客户端。
    image_ref 可为 /files/..（相对）、http://.../files/.. 或 data-url。失败/未配置 key 返回空串。"""
    try:
        from agent.tools.vision import _get_client, _local_file_to_data_url
        from langchain_core.messages import HumanMessage
        # /files 本地图 → 补全为 http → 再转 data-url（视觉模型读本地 base64 更稳）
        ref = (image_ref or "").strip()
        if ref.startswith("/files/"):
            ref = "http://localhost:8000" + ref
        if ref.startswith("http"):
            _local = _local_file_to_data_url(ref)
            if _local == "__TOO_LARGE__":
                return ""
            if _local:
                ref = _local
        client = _get_client()
        resp = client.invoke([
            HumanMessage(content=[
                {"type": "text", "text": (
                    "请用不超过100字的一句话，客观描述这张图片的主要内容（是什么图、含哪些关键文字/对象）。"
                    "如果是无内容的图标/空白图，直接回复：无有效内容")},
                {"type": "image_url", "image_url": {"url": ref}},
            ])
        ])
        txt = str(getattr(resp, "content", "")).strip()
        return txt[:300] if txt and txt != "无有效内容" else ""
    except Exception as e:
        logger.warning(f"[mm_ingest]caption 失败：{str(e)[:120]}")
        return ""


def _media_store(scene: str) -> MultimodalVectorStore:
    return MultimodalVectorStore(scene=scene)


def _entry_id(source: str, kind: str, img_name: str, page: int | None = None) -> str:
    raw = f"{source}::{kind}::{img_name}" + (f"::p{page}" if page is not None else "")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _stage_image_for_show(raw_bytes: bytes, ext: str) -> tuple[str, str]:
    """把图字节落盘 data/uploads → (展示 URL /files/<name>, data-url 喂 embedding)"""
    import uuid
    import base64
    os.makedirs(get_abs_path("data/uploads"), exist_ok=True)
    name = uuid.uuid4().hex + "." + ext.lower()
    with open(get_abs_path(os.path.join("data/uploads", name)), "wb") as f:
        f.write(raw_bytes)
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(ext.lower(), "image/png")
    data_url = f"data:{mime};base64,{base64.b64encode(raw_bytes).decode('ascii')}"
    return f"/files/{name}", data_url


# ---------------- 独立图片入库 ----------------
def _with_kb_upload_dir(files: list[str], scene: str, allowed) -> list[str]:
    """把 data/kb/<scene>/ 下的页面上传入库文件并入扫描列表（已按场景目录隔离，不过滤前缀）。"""
    kb_dir = get_abs_path(os.path.join("data", "kb", scene))
    if os.path.isdir(kb_dir):
        files = list(files) + list(listdir_with_allowed_type(kb_dir, allowed))
    return files


def ingest_independent_images(store, scene: str, src_dir: str) -> tuple[int, int]:
    allowed = tuple(chroma_conf.get("allow_multimodal_image_type", ["png", "jpg", "jpeg", "gif", "webp", "bmp"]))
    files = listdir_with_allowed_type(get_abs_path(src_dir), allowed)
    files = [f for f in files if _is_scene_file(scene, os.path.basename(f))]
    files = _with_kb_upload_dir(files, scene, allowed)
    ok = fail = 0
    md5_file = _md5_path(scene)
    for path in files:
        digest = get_file_md5_hex(path) or hashlib.md5(path.encode()).hexdigest()
        if _check_md5(md5_file, digest):
            logger.info(f"[mm_ingest]图已处理过，跳过 {os.path.basename(path)}")
            continue
        try:
            with open(path, "rb") as f:
                raw = f.read()
            ext = os.path.splitext(path)[1].lstrip(".").lower()
            # 仅图片 magic 粗检（避免把非图塞进来）
            head = raw[:16]
            img_magics = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"BM")
            if not any(head.startswith(m) for m in img_magics):
                logger.warning(f"[mm_ingest]{path} 不是有效图片，跳过")
                continue
            rel_url, data_url = _stage_image_for_show(raw, ext)
            abs_url = "http://localhost:8000" + rel_url     # 统一存 http 绝对 URL（前端 <img> 直接可显示）
            caption = _caption_image(abs_url)               # http://... 交给 caption 内部转 data-url
            text = caption or ""
            store.add_entry(
                entry_id=_entry_id(os.path.basename(path), "image", os.path.basename(rel_url)),
                text=text, image_data_url=data_url,
                source=os.path.basename(path), kind="image", image_url=abs_url,
            )
            _save_md5(md5_file, digest)
            ok += 1
            logger.info(f"[mm_ingest]独立图入库 {os.path.basename(path)}（caption {len(caption)}字）")
        except MultimodalEmbeddingError as e:
            fail += 1
            logger.error(f"[mm_ingest]{path} 向量化失败：{e}")
        except Exception as e:
            fail += 1
            logger.error(f"[mm_ingest]{path} 失败：{str(e)[:150]}", exc_info=True)
    return ok, fail


# ---------------- PDF 内嵌图入库 ----------------
def ingest_pdf_images(store, scene: str, src_dir: str) -> tuple[int, int]:
    try:
        from rag.pdf_image_extractor import extract_pdf_images
    except Exception as e:
        logger.error(f"[mm_ingest]PDF 抽图模块不可用：{e}")
        return 0, 0

    pdfs = listdir_with_allowed_type(get_abs_path(src_dir), (".pdf",))
    pdfs = [f for f in pdfs if _is_scene_file(scene, os.path.basename(f))]
    pdfs = _with_kb_upload_dir(pdfs, scene, (".pdf",))
    ok = fail = 0
    md5_file = _md5_path(scene)
    for path in pdfs:
        digest = get_file_md5_hex(path) or hashlib.md5(path.encode()).hexdigest()
        if _check_md5(md5_file, digest):
            logger.info(f"[mm_ingest]PDF已处理过，跳过 {os.path.basename(path)}")
            continue
        imgs = extract_pdf_images(path)   # 已落盘到 data/uploads
        for im in imgs:
            try:
                caption = _caption_image("http://localhost:8000" + im["img_url"])
                # 锚点文本：caption + 所属页上下文（正文兜底）
                anchor = caption or ""
                ctx = (im.get("page_text") or "").strip()
                if ctx and len(ctx) > 0:
                    anchor = (anchor + "\n" + ctx if anchor else ctx)
                store.add_entry(
                    entry_id=_entry_id(os.path.basename(path), "pdf_image", im["img_name"], im.get("page_no")),
                    text=anchor, image_data_url=im["data_url"],
                    source=os.path.basename(path), kind="pdf_image",
                    image_url="http://localhost:8000" + im["img_url"],
                    page=im.get("page_no"),
                )
                ok += 1
            except MultimodalEmbeddingError as e:
                fail += 1
                logger.error(f"[mm_ingest]{path} 图 {im.get('img_name')} 向量化失败：{e}")
            except Exception as e:
                fail += 1
                logger.error(f"[mm_ingest]{path} 图 {im.get('img_name')} 失败：{str(e)[:120]}")
        if imgs:
            _save_md5(md5_file, digest)   # 有图才记 md5（无内嵌图的 PDF 下次仍会尝试，成本低）
    return ok, fail


def main():
    ap = argparse.ArgumentParser(description="多模态图文入库")
    ap.add_argument("--scene", default="robot", choices=["robot", "sky"])
    ap.add_argument("--rebuild", action="store_true", help="清空集合后重建（忽略 md5 去重）")
    ap.add_argument("--no-images", action="store_true", help="跳过独立图入库")
    ap.add_argument("--no-pdf", action="store_true", help="跳过 PDF 内嵌图入库")
    ap.add_argument("--data-dir", default="data", help="知识源目录（默认 data/）")
    args = ap.parse_args()

    if args.rebuild:
        # 清空 md5 记录（让 rebuild 能重扫全部）
        md5f = _md5_path(args.scene)
        try:
            open(md5f, "w").close()
        except Exception:
            pass

    store = _media_store(args.scene)
    if args.rebuild:
        store.clear()
        logger.info(f"[mm_ingest]已清空集合 {store.collection.name}")

    n_ok = n_fail = 0
    if not args.no_images:
        o, f = ingest_independent_images(store, args.scene, args.data_dir)
        n_ok += o; n_fail += f
    if not args.no_pdf:
        o, f = ingest_pdf_images(store, args.scene, args.data_dir)
        n_ok += o; n_fail += f

    logger.info(f"[mm_ingest]完成：入库 {n_ok} 条，失败 {n_fail} 条；集合总量 {store.count()}")


if __name__ == "__main__":
    main()
