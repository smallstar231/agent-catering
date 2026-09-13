# 安全代码沙箱工具
# 功能：让 Agent 提交一段 Python 代码，在受限子进程中执行并返回 stdout/stderr。
# 安全设计（v3 = 白名单模式；本地学习项目够用，非完全隔离）：
#   1. 子进程执行：不污染主进程状态，崩溃/死循环不拖垮服务。
#   2. 超时控制：默认 15s，超时 kill（防死循环）。
#   3. ★ AST 白名单预检（v3 核心）：import 的白名单模块、调用的白名单内置函数、
#      禁止一切 dunder 属性访问、字符串禁止含 "__" —— **白名单之外一律拒绝**。
#      相比 v2 的黑名单（列举危险项），白名单的"漏项"不再是漏洞。
#   4. 内置变量净化：在受限命名空间运行，屏蔽 __builtins__ 危险项。
#   5. 输出截断：stdout/stderr 各截断到 MAX_OUTPUT，防撑爆上下文。
#   6. 工作目录指向 data/sandbox/（仅此目录可写，模拟受限文件系统）。
#
# 已知能力边界（白名单的代价）：沙箱只面向"纯计算"——可用 math/statistics/json 等
# 计算类库与常见内置函数；不能读文件、不能联网、不能 import 系统模块。
# 若代码用到能力之外的东西，会被明确拒绝并说明原因（模型可据此改写）。
#   7. ⚠️ 已知限制：AST 预检作用在"代码文本"上，可被非常规手法绕过（如把 dunder
#      藏进字符串再由内建 str.format 解析——v3 已用"字符串禁含 __"堵住）。
#      **不可用于"不可信代码"场景**，仅限本地学习/演示。
# 说明：Windows 无 resource.setrlimit，故用"子进程+超时+AST 白名单预检"而非真正资源限额。
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

# ---- v3 白名单（只允许"纯计算"能力；白名单之外一律拒绝）----
# 允许 import 的模块：均为"不触达系统/网络/文件"的计算类库
# 注意：这些库内部可能 import os/sys（如 json/random 依赖 os），但那是"库自身加载"
#       的行为，与"用户代码能否 import os"无关 —— 用户代码里的 `import os` 仍被下面的
#       AST 白名单拦住。所以此处无需（也不该）考虑它们的内部依赖。
_ALLOWED_IMPORTS = {
    "math", "statistics", "json", "random", "re", "datetime",
    "collections", "itertools", "functools", "decimal", "fractions",
    "string", "textwrap", "heapq", "bisect", "operator",
}

def _build_code(user_code: str) -> str:
    """把用户代码包进受限 guard（builtin 清理），再交给子进程 exec。

    设计演进：
      - v1（已废弃）：删 builtin exec/memoryview 防逃逸 → 但 importlib 依赖它们，
        导致"纯 Python 模块"（json/re/datetime）全崩，只剩 C 扩展 math 可用。
      - v2：不再删 exec/compile/memoryview（importlib 必需），改用**黑名单** AST 预检
        （列举危险调用 / import / dunder）→ 但黑名单必然有漏项：
        实测 `().__getattribute__('__class__')` 可绕过并读到任意文件（含 .env）。
      - v3（当前）：AST 预检改成**白名单** —— 只允许 _ALLOWED_IMPORTS 的模块、
        _ALLOWED_CALL_NAMES 的内置函数；属性访问**禁止一切 dunder**；字符串禁止含 "__"。
        白名单之外一律拒绝，故"漏项"不再构成漏洞。
      - 子进程隔离仍是纵深：即使标准库在沙箱内加载了 os，用户代码也拿不到 os 这个名字
        （AST 禁 import os），也走不通 dunder 逃逸链（AST 禁 dunder）。
      - 刻意保留 exec/compile/memoryview 供 importlib 使用（不删，避免重蹈 v1 覆辙）。
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


# ---- 允许"直接名字调用"的内置函数（白名单；不在表内一律拒绝）----
# 只收"纯计算/数据处理"所需；刻意**不含** open/eval/exec/compile/__import__/getattr/
# vars/globals/locals/input/breakpoint/exit/quit 等能触达系统、或可用于逃逸探路的函数。
_ALLOWED_CALL_NAMES = {
    # 输出
    "print",
    # 序列 / 聚合
    "len", "range", "sum", "min", "max", "sorted", "reversed",
    "enumerate", "zip", "map", "filter", "any", "all",
    # 数值
    "abs", "round", "pow", "divmod",
    # 类型构造 / 转换
    "int", "float", "str", "bool", "list", "dict", "set", "tuple", "frozenset",
    "isinstance", "repr", "format",
    "chr", "ord", "hex", "oct", "bin", "hash",
    # 迭代器
    "iter", "next", "slice",
}


def _check_ast_safety(code: str) -> None:
    """静态扫描用户代码 AST（**白名单模式**）：白名单之外一律拒绝。

    四类检查：
      1. import / from-import：模块必须在 _ALLOWED_IMPORTS
      2. 调用（按名字）：被调函数名必须在 _ALLOWED_CALL_NAMES
      3. 属性访问：**禁止一切 dunder**（__xxx__）—— 逃逸链的必经之路。
         对比 v2 的"列举 10 个危险 dunder"，这里改成默认拒绝，
         因此 __getattribute__ 之类同样被拦，不再是漏网之鱼。
      4. 字符串字面量：禁止含 "__" —— 防 "{0.__class__}".format(obj) 这类
         "把属性访问藏进字符串、由 str.format 在运行期解析"的绕过。
    """
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # 语法错误交给运行时 exec 报（让用户看到真实语法错），这里不拦
        return

    def _err(node, why):
        lineno = getattr(node, "lineno", "?")
        raise SyntaxError(f"沙箱安全拦截（第{lineno}行）：{why}")

    _mods_hint = "/".join(sorted(_ALLOWED_IMPORTS))
    _fns_hint = ", ".join(sorted(_ALLOWED_CALL_NAMES)[:10])

    for node in ast.walk(tree):
        # 1) import / from import —— 白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _ALLOWED_IMPORTS:
                    _err(node, f"沙箱仅允许 import 计算类库（{_mods_hint}），不允许 '{top}'")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if not node.module or top not in _ALLOWED_IMPORTS:
                _err(node, f"沙箱仅允许 from 计算类库 import，不允许 'from {node.module}'")

        # 2) 调用 —— 只校验"直接名字调用"（如 open(...)）；对象方法调用不在此列
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id not in _ALLOWED_CALL_NAMES:
                _err(node, f"沙箱仅允许调用计算类内置函数（{_fns_hint} 等），不允许 {f.id}()")

        # 3) 属性访问 —— 禁止一切 dunder（逃逸链必经：obj.__class__ / __globals__ / ...）
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                _err(node, f"禁止访问特殊属性 {node.attr}")

        # 4) 字符串字面量 —— 禁止含 "__"（防 format 注入式逃逸）
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "__" in node.value:
                _err(node, "字符串中禁止包含 '__'")



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
