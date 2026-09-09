# 网页正文读取工具
# 功能：抓取指定 URL 的正文纯文本，供 Agent 阅读网页内容（配合 web_search 补全细节）
# 抓取策略（按顺序尝试）：
#   1. 直连目标 URL 抓 HTML → 去 script/style/标签 得正文纯文本（国内网络可直接访问）
#   2. 若直连失败，尝试经 Jina Reader（https://r.jina.ai/<url>，免 key）——部分网络不可达时自动跳过
# 安全：
#   - SSRF 防护：仅允许 http/https；拒绝指向内网/环回/保留地址的 URL（避免被诱导访问内网资源）
#   - 可配置白名单主机（env PAGE_READ_ALLOW_HOSTS，逗号分隔）放宽限制

import os
import re
import socket
import ipaddress
from urllib.parse import urlparse
import httpx
from utils.logger_handler import logger

JINA_BASE = "https://r.jina.ai/"
DEFAULT_MAX_CHARS = 1500
TIMEOUT = 15.0
# UA：部分站点对无 UA 的请求返回 403
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _is_private_ip(ip_str: str) -> bool:
    """判断 IP 是否为内网/环回/保留/链路本地等非公网地址"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 无法解析 → 保守拦截
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _host_allowed(host: str) -> bool:
    """host 是否在显式白名单中（env PAGE_READ_ALLOW_HOSTS，逗号分隔）。
    注意：只有显式配置了白名单且命中，内网/保留地址主机才会被放行；空配置返回 False（内网一律拦截）。"""
    allow_hosts = os.getenv("PAGE_READ_ALLOW_HOSTS", "")
    if not allow_hosts:
        return False
    allowed = {h.strip().lower() for h in allow_hosts.split(",") if h.strip()}
    return host.lower() in allowed


def _guard_url(url: str) -> str | None:
    """
    校验 URL 是否可安全抓取。
    返回：None 表示通过；否则返回被拒原因文案。
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        return f"URL 解析失败：{e}"
    if parsed.scheme not in ("http", "https"):
        return f"仅支持 http/https 链接，当前为 {parsed.scheme or '空'} 协议"
    host = parsed.hostname
    if not host:
        return "链接缺少主机名"
    # 解析主机所有 IP，任一是内网即拒绝（防 DNS rebinding：全部记录都检查）
    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"无法解析主机 {host}"
    for info in infos:
        ip = info[4][0]
        if _is_private_ip(ip):
            # 内网地址：仅当该 host 在白名单时才放行，否则拒绝
            if _host_allowed(host):
                return None
            return f"目标 {host}({ip}) 不是公网地址，已拒绝抓取"
    return None


def _strip_html(html: str) -> str:
    """从 HTML 中抽取正文纯文本（去 script/style/标签/多余空白）"""
    if not html:
        return ""
    text = html
    # 去掉 script/style/head/noscript 内容块
    text = re.sub(r"(?is)<(script|style|noscript|head|iframe|svg)[^>]*>.*?</\1>", " ", text)
    # 去掉注释
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    # 去所有标签
    text = re.sub(r"<[^>]+>", " ", text)
    # 去大量空白 / 把换行规整
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _fetch_direct(url: str) -> str | None:
    """直连抓取 URL 并抽取正文；失败返回 None"""
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=_HEADERS)
        if resp.status_code != 200:
            logger.warning(f"[page_read]直连 HTTP {resp.status_code} for {url}")
            return None
        return _strip_html(resp.text)
    except Exception as e:
        logger.debug(f"[page_read]直连失败 {url}: {str(e)[:100]}")
        return None


def _fetch_via_jina(url: str) -> str | None:
    """经 Jina Reader 抓取（免 key）；网络不可达则返回 None"""
    try:
        resp = httpx.get(JINA_BASE + url, timeout=TIMEOUT, follow_redirects=True, headers=_HEADERS)
        if resp.status_code != 200:
            return None
        return resp.text.strip()
    except Exception as e:
        logger.debug(f"[page_read]jina 失败 {url}: {str(e)[:100]}")
        return None


def page_read(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """
    读取网页正文
    入参：url - 目标网页链接
    返回：网页正文纯文本（截取前 max_chars 字符）。失败返回原因文案，不抛异常。
    """
    url = (url or "").strip()
    # 无 scheme 时才补 https://（已有 ftp:// 等 scheme 的不补，交给后续 guard 拒绝）
    if url and "://" not in url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    blocked = _guard_url(url)
    if blocked:
        return f"【网页读取被拒】{blocked}"

    # 策略 1：直连抓 HTML
    text = _fetch_direct(url)
    # 策略 2：直连失败 → 经 Jina（需网络可达）
    if not text:
        text = _fetch_via_jina(url)

    if not text:
        return f"【网页读取失败】无法获取 {url} 的正文（网络不可达或站点限制抓取）。"

    if len(text) > max_chars:
        text = text[:max_chars] + "...(内容过长已截断)"
    logger.info(f"[page_read]成功读取 {url}（{len(text)} 字符）")
    return text


if __name__ == '__main__':
    print(page_read("https://example.com"))
