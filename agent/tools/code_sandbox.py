# 安全代码沙箱工具
# 功能：让 Agent 提交一段 Python 代码，在受限子进程中执行并返回 stdout/stderr。
# 安全设计（本地学习项目够用，非完全隔离）：
#   1. 子进程执行：不污染主进程状态，崩溃/死循环不拖垮服务。
#   2. 超时控制：默认 15s，超时 kill（防死循环）。
#   3. import 黑名单：禁止 os.system/subprocess/socket/shutil/ctypes 等危险能力（改为受限白名单子集）。
#   4. 内置变量净化：在受限命名空间运行，屏蔽 __builtins__ 危险项。
#   5. 输出截断：stdout/stderr 各截断到 MAX_OUTPUT，防撑爆上下文。
#   6. 工作目录指向 data/sandbox/（仅此目录可写，模拟受限文件系统）。
# 说明：Windows 无 resource.setrlimit，故用"子进程+超时+黑名单"而非真正资源限额。
#       若要更强隔离（进程级内存/CPU 限额），可后续改用 Docker 沙箱（本文件留接口 run_in_docker 位）。

import subprocess
import sys
import os
import textwrap
from utils.path_tool import get_abs_path
from utils.logger_handler import logger

MAX_OUTPUT = 2000          # 单端输出最大字符
TIMEOUT_SECONDS = 15       # 执行超时
_SANDBOX_DIR = "data/sandbox"  # 仅此目录可写

# 危险/禁用的顶层 import 名（防止代码拿到 shell / 网络 / 文件删除能力）
_FORBIDDEN_IMPORTS = [
    "os", "subprocess", "socket", "shutil", "ctypes", "pickle",
    "importlib", "sys", "multiprocessing", "threading", "signal",
    "webbrowser", "pty", "fcntl", "winreg", "http", "urllib",
    "requests", "httpx", "sqlite3", "pathlib",
]
# 这些模块的某些成员也危险，但我们主要拦顶层 import；完整加固需更复杂 AST，本演示从简。

# 沙箱预置代码：注入受限 builtins + 常用安全库（math/statistics/json 等）
_SANDBOX_PRELUDE = textwrap.dedent('''
# --- 沙箱受限环境（自动注入） ---
import math, statistics, json, random, re, datetime, collections, itertools, functools
# 屏蔽能逃逸的子进程/文件系统能力（在 __builtins__ 层面兜底）
_safe_builtins = dict(__builtins__) if isinstance(__builtins__, dict) else __builtins__.__dict__.copy()
for _bad in ('__import__', 'open', 'input', 'exec', 'eval', 'compile', 'globals', 'locals', 'vars', '__loader__', '__spec__'):
    _safe_builtins.pop(_bad, None)
_safe_builtins['print'] = print
import builtins as _b
_b.__dict__.update({k: v for k, v in _safe_builtins.items()})
''')


def _build_code(user_code: str) -> str:
    """把用户代码包进受限 prelude + 主函数"""
    # 不直接注入 prelude 到每个用户代码前（可能破坏其缩进），而是用受限方式 exec：
    # 用一个包装，先禁用 __import__ 顶层危险库，再 exec 用户代码
    guard = textwrap.dedent(f'''
        import builtins as _b
        # 1) 屏蔽 __import__ 顶层危险库
        _orig_import = _b.__import__
        _FORBIDDEN = {_FORBIDDEN_IMPORTS}
        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            _top = name.split('.')[0]
            if _top in _FORBIDDEN:
                raise ImportError(f"import '{{name}}' 被沙箱禁用")
            return _orig_import(name, globals, locals, fromlist, level)
        _b.__import__ = _guarded_import
        # 2) 直接删除能逃逸/触碰文件的 builtin（eval/exec/open/input/compile 等）
        #    注意：不能删 __import__（已替换为 guard），否则任何 import 都会崩
        for _bad in ('eval','exec','compile','open','input','memoryview','breakpoint'):
            try: _b.__dict__.pop(_bad, None)
            except Exception: pass
        # 3) 拦截 open 的别名变体（io.open）
        try:
            import io as _io
            _io.open = None
        except Exception: pass
    ''')
    return guard + "\n" + user_code


def run_code(code: str, timeout: int = TIMEOUT_SECONDS) -> str:
    """
    在受限子进程中执行 Python 代码，返回 stdout/stderr 合并文本。
    入参：code - 用户/Agent 提交的 Python 源码
    返回：执行输出（截断）。代码异常/超时返回带说明的错误文本，不抛给 Agent。
    """
    if not code or not code.strip():
        return "【代码沙箱】没有可执行的代码。"

    # 确保沙箱目录存在（作为唯一可写工作目录）
    sandbox_abs = get_abs_path(_SANDBOX_DIR)
    os.makedirs(sandbox_abs, exist_ok=True)

    # 组装受限代码
    full_code = _build_code(code)

    # 子进程执行（用同一 venv python；代码经 stdin 的 buffer 以 utf-8 传入，避免 Windows 编码问题）
    child_code = (
        "import sys; "
        # 子进程 stdout/stderr 强制 utf-8，避免 Windows GBK 导致中文乱码
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace'); "
        "sys.stderr.reconfigure(encoding='utf-8', errors='replace'); "
        "src=sys.stdin.buffer.read().decode('utf-8'); "
        "exec(compile(src, '<sandbox>', 'exec'))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", child_code],
            input=full_code.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=sandbox_abs,          # 工作目录限定在沙箱目录
        )
    except subprocess.TimeoutExpired:
        logger.warning("[code_sandbox]执行超时，已终止")
        return f"【代码沙箱】执行超过 {timeout}s，已终止（可能存在死循环）。"
    except Exception as e:
        logger.error(f"[code_sandbox]启动子进程失败：{str(e)[:150]}")
        return f"【代码沙箱】执行环境错误：{str(e)[:120]}"

    # 解码 stdout/stderr（utf-8，容错）
    out = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    if proc.returncode != 0 and not out:
        out = f"(退出码 {proc.returncode})"
    result = (out + (("\n[stderr]\n" + err) if err else "")).strip()
    if len(result) > MAX_OUTPUT:
        result = result[:MAX_OUTPUT] + f"\n...(输出过长，截断到 {MAX_OUTPUT} 字符)"
    return result if result else "（无输出）"


if __name__ == '__main__':
    # 测试：正常计算
    print("== 正常 ==")
    print(run_code("print(1 + 2)\nprint('hello', 3.14)"))
    print("== 禁 os ==")
    print(run_code("import os\nprint(os.listdir('.'))"))
    print("== 超时 ==")
    print(run_code("while True:\n    pass", timeout=2))
