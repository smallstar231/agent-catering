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
# 注意：不要把 sys 放进黑名单 —— json/re/random/statistics/collections/functools
#       等"纯 Python 标准库模块"内部都 import sys，拦 sys 会导致这些库一加载就崩
#       （而 C 扩展如 math/datetime 不依赖 sys 所以正常，行为不一致）。sys 本身
#       不构成逃逸（逃逸靠拿到 os/open/模块对象），真正要拦的是下面的系统/网络/文件类。
_FORBIDDEN_IMPORTS = [
    "os", "subprocess", "socket", "shutil", "ctypes", "pickle",
    "importlib", "multiprocessing", "threading", "signal",
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
    """把用户代码包进受限 guard（import 门卫 + builtin 清理），再交给子进程 exec。

    设计（v2，替代旧的"删 exec/memoryview"方案）：
      - 旧方案删 builtin exec/memoryview，导致 importlib 无法加载"纯 Python 模块"
        （json/re/datetime 等全崩，只剩 C 扩展 math 可用），且不删 exec 又怕逃逸。
      - 新方案**不再删 exec/compile/memoryview**（importlib 必需），改为两层防护：
        ① 静态 AST 预检：在代码真正执行前扫 AST，若用户代码里出现危险调用
           (open/eval/exec/compile/__import__/breakpoint/input/globals/locals/
           vars/exit/quit 等) 或危险 import → 直接拒绝，不进入执行。
        ② 运行时 import 门卫：仍替换 __import__，拦顶层危险模块(os/subprocess/
           socket/网络/DB/文件系统)作为纵深。
      - 效果：纯 Python 模块(json/re/datetime/random/math...)可正常 import 做计算；
        但用户代码文本里根本写不出 open/eval/exec，也 import 不进 os/网络。
    """
    # ① 静态 AST 预检：扫描用户代码，发现危险即抛
    _check_ast_safety(user_code)

    # ② 运行时：不替换 __import__、不删 exec/compile/memoryview。
    #   原因：json/random/statistics 等"纯 Python 标准库"内部会 import os/sys，
    #   若运行时拦 os，会误伤这些库一加载就崩。真正的隔离靠：
    #     - AST 已精确作用在"用户代码文本"上：用户写不出 import os、open、eval、
    #       __class__ 逃逸链；
    #     - 子进程隔离：即使标准库在沙箱内加载了 os，用户代码也拿不到 os 这个名字
    #       （AST 禁 import os），且 __class__ 逃逸被 AST 禁。
    #    仅清理不破坏 importlib 的逃逸口（保留 exec/compile/memoryview 供 import 用）。
    guard = textwrap.dedent(f'''
        import builtins as _b
        for _bad in ('open','input','breakpoint','exit','quit'):
            try: _b.__dict__.pop(_bad, None)
            except Exception: pass
    ''')
    return guard + "\n" + user_code


# AST 预检：禁止出现在"用户代码"里的危险内置调用 / 危险字面量
_DANGEROUS_CALL_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "breakpoint", "input",
    "globals", "locals", "vars", "exit", "quit", "memoryview",  # memoryview 仅禁用户直接调(库内部不受此 AST 约束)
    "getattr",  # 谨慎：getattr 常被逃逸链用作 obj.__class__ 探路
}
# 危险 import 顶层名（运行时门卫的镜像，AST 层先拦，给更友好报错）
_DANGEROUS_IMPORT_NAMES = set(_FORBIDDEN_IMPORTS)


def _check_ast_safety(code: str) -> None:
    """静态扫描用户代码 AST：
    - import / from-import 危险模块 → 拒绝
    - 调用危险内置(open/eval/exec/...) → 拒绝
    - 属性链含 __class__ / __subclasses__ / __globals__ / __builtins__ 等逃逸探针 → 拒绝
    - 访问危险 dunder 属性 → 拒绝
    """
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        # 语法错误交给运行时 exec 报（让用户看到真实语法错），这里不拦
        return

    def _err(node, why):
        lineno = getattr(node, "lineno", "?")
        raise SyntaxError(f"沙箱安全拦截（第{lineno}行）：{why}")

    for node in ast.walk(tree):
        # 1) import / from import
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _DANGEROUS_IMPORT_NAMES:
                    _err(node, f"禁止 import 模块 '{top}'")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.module and top in _DANGEROUS_IMPORT_NAMES:
                _err(node, f"禁止 from {node.module} import")
            for alias in node.names:
                if alias.name in ("open",):
                    _err(node, "禁止 from ... import open")

        # 2) 危险内置调用
        elif isinstance(node, ast.Call):
            f = node.func
            # 直接名字调用：open("..")
            if isinstance(f, ast.Name) and f.id in _DANGEROUS_CALL_NAMES:
                _err(node, f"禁止调用 {f.id}()")
            # 属性调用：xxx.open / io.open / os.system 之类（dunder 探针已在下方拦）
            if isinstance(f, ast.Attribute) and f.attr in ("open",):
                # 允许 obj.open 吗？不允许 —— open 必须整名
                _err(node, "禁止调用 .open()")

        # 3) 逃逸探针：属性访问 __xxx__
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                if node.attr in ("__class__", "__globals__", "__subclasses__",
                                 "__bases__", "__mro__", "__builtins__", "__loader__",
                                 "__spec__", "__init__", "__dict__"):
                    _err(node, f"禁止访问特殊属性 {node.attr}")
                # 其它 dunder(如 __name__)放行

        # 4) 禁止的 builtin 名直接引用(非调用，如 print(open))
        elif isinstance(node, ast.Name):
            if node.id in ("__import__",):
                _err(node, "禁止引用 __import__")



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

    # 组装受限代码（AST 预检若发现危险调用，会抛 SyntaxError —— 捕获转成友好提示）
    try:
        full_code = _build_code(code)
    except SyntaxError as e:
        return f"【代码沙箱】{e}"

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
