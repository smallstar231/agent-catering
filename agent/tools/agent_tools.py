# Agent 工具定义模块
# 功能：定义 Agent 可以调用的 7 个工具函数
# 被 agent/react_agent.py 导入，注册到 ReAct Agent 中
# 工具列表：rag_summarize、get_weather、get_user_location、get_user_id、get_current_month、fetch_external_data、fill_context_for_report

import os
import random                                        # 随机数（用于模拟数据）
import json                                          # JSON 解析（用于苍穹外卖接口调用）
from utils.logger_handler import logger              # 日志记录器
from langchain_core.tools import tool                # LangChain 的 @tool 装饰器，将普通函数转为 Agent 工具

from rag.rag_service import RagSummarizeService      # RAG 总结服务（用于 rag_summarize 工具）
from utils.prompt_loader import load_rag_prompts_sky # 苍穹外卖 RAG 提示词加载器
from utils.config_handler import agent_conf          # Agent 配置（外部数据文件路径）
from utils.path_tool import get_abs_path             # 路径工具

# ---- 模块级初始化 ----
# 创建 RAG 总结服务实例（会初始化向量库和 LLM 链）
rag = RagSummarizeService()

# 创建苍穹外卖 RAG 总结服务实例（使用苍穹外卖提示词 + 独立集合）
rag_sky = RagSummarizeService(prompt_loader=load_rag_prompts_sky, scene="sky")

# 模拟数据：用户 ID 列表
user_ids = ["1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1010",]

# 模拟数据：月份列表
month_arr = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06",
             "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", ]

# 外部用户数据缓存（首次使用时从 CSV 文件加载）
external_data = {}


# ---- 工具 1：RAG 检索总结 ----
@tool(description="从向量存储中检索参考资料")
def rag_summarize(query: str) -> str:
    """
    从 Chroma 向量库中检索与 query 相关的文档，交给 LLM 总结后返回
    入参：query - 检索词，如 "扫地机器人怎么保养"
    返回：LLM 基于检索结果生成的总结文本
    """
    # 调用 RagSummarizeService 的 rag_summarize 方法（检索 + 总结）
    return rag.rag_summarize(query)


# ---- 工具 2：天气查询（模拟数据） ----
@tool(description="获取指定城市的天气，以消息字符串的形式返回")
def get_weather(city: str) -> str:
    """
    获取指定城市的天气信息（当前为模拟数据，返回固定值）
    入参：city - 城市名，如 "深圳"
    返回：天气信息字符串
    """
    # 返回固定的模拟天气数据（实际项目中应调用真实天气 API）
    return f"城市{city}天气为晴天，气温26摄氏度，空气湿度50%，南风1级，AQI21，最近6小时降雨概率极低"


# ---- 工具 3：获取用户位置（模拟数据） ----
@tool(description="获取用户所在城市的名称，以纯字符串形式返回")
def get_user_location() -> str:
    """
    获取用户所在城市（当前为模拟数据，随机返回一个城市）
    入参：无
    返回：城市名称字符串
    """
    # 随机返回一个城市（实际项目中应获取真实地理位置）
    return random.choice(["深圳", "合肥", "杭州"])


# ---- 工具 4：获取用户 ID（模拟数据） ----
@tool(description="获取用户的ID，以纯字符串形式返回")
def get_user_id() -> str:
    """
    获取当前用户的 ID（当前为模拟数据，随机返回一个 ID）
    入参：无
    返回：用户 ID 字符串，如 "1001"
    """
    return random.choice(user_ids)


# ---- 工具 5：获取当前月份（模拟数据） ----
@tool(description="获取当前月份，以纯字符串形式返回")
def get_current_month() -> str:
    """
    获取当前月份（当前为模拟数据，随机返回一个月份）
    入参：无
    返回：月份字符串，格式 "YYYY-MM"
    """
    return random.choice(month_arr)


# ---- 内部函数：加载外部用户数据 ----
def generate_external_data():
    """
    从 CSV 文件加载外部用户使用数据到 external_data 字典
    数据结构：{user_id: {month: {"特征": x, "效率": x, "耗材": x, "对比": x}}}
    仅首次调用时加载，之后从缓存读取
    """
    # 如果缓存为空，才加载（懒加载模式）
    if not external_data:
        # 从配置中获取 CSV 文件路径
        external_data_path = get_abs_path(agent_conf["external_data_path"])

        # 安全检查：文件是否存在
        if not os.path.exists(external_data_path):
            raise FileNotFoundError(f"外部数据文件{external_data_path}不存在")

        # 读取 CSV 文件
        with open(external_data_path, "r", encoding="utf-8") as f:
            # f.readlines()[1:] 读取所有行并跳过第一行（表头）
            for line in f.readlines()[1:]:
                # 按逗号分割每行，得到各字段
                arr: list[str] = line.strip().split(",")

                # 提取各字段值，去掉引号
                user_id: str = arr[0].replace('"', "")      # 用户 ID
                feature: str = arr[1].replace('"', "")       # 特征
                efficiency: str = arr[2].replace('"', "")    # 效率
                consumables: str = arr[3].replace('"', "")   # 耗材
                comparison: str = arr[4].replace('"', "")    # 对比
                time: str = arr[5].replace('"', "")          # 月份

                # 如果该用户还没有记录，初始化空字典
                if user_id not in external_data:
                    external_data[user_id] = {}

                # 存入缓存：external_data[用户ID][月份] = {各字段}
                external_data[user_id][time] = {
                    "特征": feature,
                    "效率": efficiency,
                    "耗材": consumables,
                    "对比": comparison,
                }


# ---- 工具 6：获取外部用户数据 ----
@tool(description="从外部系统中获取指定用户在指定月份的使用记录，以纯字符串形式返回， 如果未检索到返回空字符串")
def fetch_external_data(user_id: str, month: str) -> str:
    """
    从外部数据中获取指定用户在指定月份的使用记录
    入参：user_id - 用户 ID，month - 月份（格式 "YYYY-MM"）
    返回：使用记录字典，或空字符串（未找到时）
    """
    # 确保数据已加载（懒加载，只在首次调用时读 CSV）
    generate_external_data()

    try:
        # 从缓存中查找：external_data[user_id][month]
        return external_data[user_id][month]
    except KeyError:
        # 找不到该用户或该月份的数据
        logger.warning(f"[fetch_external_data]未能检索到用户：{user_id}在{month}的使用记录数据")
        return ""


# ---- 工具 7：触发报告上下文注入 ----
@tool(description="无入参，无返回值，调用后触发中间件自动为报告生成的场景动态注入上下文信息，为后续提示词切换提供上下文信息")
def fill_context_for_report():
    """
    触发中间件为报告场景注入上下文
    这个工具本身不做任何事，它的作用是触发 middleware.py 中的监控逻辑
    当 middleware 检测到这个工具被调用时，会将 runtime.context["report"] 设为 True
    从而触发提示词切换（从 main_prompt 切换到 report_prompt）
    """
    return "fill_context_for_report已调用"


# ============================================================
# 苍穹外卖场景工具（新增）
# 当 config/agent.yml 的 scene: sky 时生效
# 所有工具通过 HTTP 调用苍穹外卖 Spring Boot 后端 API
# ============================================================

# 苍穹外卖后端 API 基础地址（与 vue.config.js 代理目标一致）
SKY_BASE_URL = "http://localhost:8080/admin"

# 苍穹外卖登录凭证缓存
_sky_token: str | None = None
_sky_login_url = "http://localhost:8080/admin/employee/login"

# 从环境变量读取管理员凭证，避免硬编码凭据泄露
# 可在 .env 文件中设置: SKY_ADMIN_USERNAME=admin  SKY_ADMIN_PASSWORD=yourpassword
import os as _os
_sky_login_data = {
    "username": _os.getenv("SKY_ADMIN_USERNAME", "admin"),
    "password": _os.getenv("SKY_ADMIN_PASSWORD", "123456"),
}


def _sky_refresh_token():
    """
    获取苍穹外卖管理员登录 token
    用于调用需要认证的管理端 API
    """
    global _sky_token
    try:
        import urllib.request
        import json

        data = json.dumps(_sky_login_data).encode("utf-8")
        req = urllib.request.Request(_sky_login_url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 1:
                _sky_token = result["data"]["token"]
                logger.info("[_sky_refresh_token]登录成功，已获取 token")
            else:
                logger.error(f"[_sky_refresh_token]登录失败：{result}")
    except Exception as e:
        logger.error(f"[_sky_refresh_token]登录出错：{str(e)}")


def _sky_api_get(endpoint: str, params: dict | None = None) -> str:
    """
    内部函数：调用苍穹外卖 Spring Boot 后端 GET 接口（自动携带 token）
    入参：endpoint - API 路径（如 /dish/page），params - 查询参数（可选）
    返回：响应 JSON 的字符串形式
    """
    # 确保 token 已获取
    if _sky_token is None:
        _sky_refresh_token()

    try:
        import urllib.request
        import urllib.parse
        import json

        url = f"{SKY_BASE_URL}{endpoint}"
        if params:
            filtered_params = {k: v for k, v in params.items() if v is not None}
            if filtered_params:
                url += "?" + urllib.parse.urlencode(filtered_params)

        req = urllib.request.Request(url, method="GET")
        req.add_header("Content-Type", "application/json")
        if _sky_token:
            req.add_header("token", _sky_token)

        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode("utf-8")
            # 格式化输出，便于 Agent 阅读
            try:
                parsed = json.loads(result)
                return json.dumps(parsed, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                return result
    except urllib.error.HTTPError as e:
        if e.code == 401 and _sky_token is not None:
            # token 过期，重新登录再试一次
            _sky_refresh_token()
            return _sky_api_get(endpoint, params)
        logger.error(f"[sky_api]HTTP错误 {e.code}: {endpoint}")
        return f"请求失败，HTTP状态码：{e.code}"
    except urllib.error.URLError as e:
        logger.error(f"[sky_api]网络错误: {endpoint} - {e.reason}")
        return f"网络错误：{e.reason}。请确认苍穹外卖后端服务是否已启动（http://localhost:8080）"
    except Exception as e:
        logger.error(f"[sky_api]未知错误: {endpoint} - {str(e)}")
        return f"请求出错：{str(e)}"


# ---- 内部函数：格式化苍穹外卖数据为纯文本 ----
_STATUS_MAP = {1: "待付款", 2: "待接单", 3: "已接单", 4: "配送中", 5: "已完成", 6: "已取消"}


def _sky_format_time(time_arr: list | None) -> str:
    """将 [2026, 3, 22, 17, 38, 6] 格式转为 2026-03-22 17:38"""
    if not time_arr or len(time_arr) < 5:
        return ""
    return f"{time_arr[0]}-{time_arr[1]:02d}-{time_arr[2]:02d} {time_arr[3]:02d}:{time_arr[4]:02d}"


def _sky_format_dishes(raw_json: str) -> str:
    """格式化菜品数据为纯文本"""
    try:
        import json
        data = json.loads(raw_json)
        if data.get("code") != 1:
            return raw_json
        records = data.get("data", {}).get("records", [])
        total = data.get("data", {}).get("total", 0)
        lines = [f"共查询到 {total} 个菜品", "-" * 60]
        for r in records:
            name = r.get("name", "未知")
            price = r.get("price", 0)
            status = "在售" if r.get("status") == 1 else "停售"
            cat_id = r.get("categoryId", "")
            lines.append(f"{name} | ¥{price:.2f} | {status} | 分类ID: {cat_id}")
        return "\n".join(lines)
    except Exception:
        return raw_json


def _sky_format_categories(raw_json: str, is_list: bool = False) -> str:
    """格式化分类数据为纯文本"""
    try:
        import json
        data = json.loads(raw_json)
        if data.get("code") != 1:
            return raw_json

        if is_list:
            records = data.get("data", [])
            lines = [f"共查询到 {len(records)} 个分类", "-" * 60]
            for r in records:
                name = r.get("name", "未知")
                typ = "菜品" if r.get("type") == 1 else "套餐"
                status = "启用" if r.get("status") == 1 else "禁用"
                sort = r.get("sort", "")
                lines.append(f"{name} | {typ} | {status} | 排序: {sort}")
        else:
            records = data.get("data", {}).get("records", [])
            total = data.get("data", {}).get("total", 0)
            lines = [f"共查询到 {total} 个分类", "-" * 60]
            for r in records:
                name = r.get("name", "未知")
                typ = "菜品" if r.get("type") == 1 else "套餐"
                status = "启用" if r.get("status") == 1 else "禁用"
                lines.append(f"{name} | {typ} | {status}")
        return "\n".join(lines)
    except Exception:
        return raw_json


def _sky_format_setmeals(raw_json: str) -> str:
    """格式化套餐数据为纯文本"""
    try:
        import json
        data = json.loads(raw_json)
        if data.get("code") != 1:
            return raw_json
        records = data.get("data", {}).get("records", [])
        total = data.get("data", {}).get("total", 0)
        lines = [f"共查询到 {total} 个套餐", "-" * 60]
        for r in records:
            name = r.get("name", "未知")
            price = r.get("price", 0)
            status = "在售" if r.get("status") == 1 else "停售"
            desc = r.get("description", "")
            lines.append(f"{name} | ¥{price:.2f} | {status}")
            if desc:
                lines.append(f"  说明: {desc}")
        return "\n".join(lines)
    except Exception:
        return raw_json


def _sky_format_orders(raw_json: str) -> str:
    """格式化订单数据为纯文本"""
    try:
        import json
        data = json.loads(raw_json)
        if data.get("code") != 1:
            return raw_json
        records = data.get("data", {}).get("records", [])
        total = data.get("data", {}).get("total", 0)
        lines = [f"共查询到 {total} 笔订单", "-" * 60]
        for r in records:
            number = r.get("number", "")
            status_text = _STATUS_MAP.get(r.get("status"), "未知")
            amount = r.get("amount", 0)
            order_time = _sky_format_time(r.get("orderTime"))
            dishes = r.get("orderDishes", "")
            consignee = r.get("consignee", "")
            phone = r.get("phone", "")
            lines.append(f"订单: {number}")
            lines.append(f"状态: {status_text} | 金额: ¥{amount:.2f} | 时间: {order_time}")
            lines.append(f"菜品: {dishes}")
            lines.append(f"客户: {consignee} {phone}")
            lines.append("")
        return "\n".join(lines)
    except Exception:
        return raw_json


def _sky_format_report(raw_json: str, report_type: str) -> str:
    """格式化报表数据为纯文本，默认标注查询范围为最近一年"""
    try:
        import json
        data = json.loads(raw_json)
        if data.get("code") != 1:
            return raw_json
        d = data.get("data", {})
        lines = [f"📊 {report_type}经营报表（数据范围：最近一年）"]
        lines.append("-" * 50)
        if report_type == "turnover":
            lines.append(f"日期范围: {d.get('dateList', '')}")
            lines.append(f"营业额: {d.get('turnoverList', '')}")
        elif report_type == "order":
            lines.append(f"日期范围: {d.get('dateList', '')}")
            lines.append(f"订单数: {d.get('orderCountList', '')}")
            lines.append(f"有效订单数: {d.get('validOrderCountList', '')}")
            lines.append(f"订单完成率: {d.get('orderCompletionRate', '')}")
        elif report_type == "dish":
            lines.append(f"销量排名Top10（数据范围：最近一年）：")
            name_list = d.get("nameList", "").split(",") if d.get("nameList") else []
            number_list = d.get("numberList", "").split(",") if d.get("numberList") else []
            for i, name in enumerate(name_list[:10]):
                count = number_list[i] if i < len(number_list) else "0"
                lines.append(f"  {i+1}. {name} - 销量: {count}")
        elif report_type == "user":
            lines.append(f"日期范围: {d.get('dateList', '')}")
            lines.append(f"新增用户: {d.get('newUserList', '')}")
            lines.append(f"总用户数: {d.get('totalUserList', '')}")
        return "\n".join(lines)
    except Exception:
        return raw_json


# ---- 工具 8：苍穹外卖 RAG 检索 ----
@tool(description="从苍穹外卖知识库中检索相关资料，如菜品介绍、运营规则、促销政策等")
def sky_rag_summarize(query: str) -> str:
    """
    从 Chroma 向量库中检索与 query 相关的苍穹外卖资料，交给 LLM 总结后返回
    入参：query - 检索词，如 "宫保鸡丁"
    返回：LLM 基于检索结果生成的总结文本
    """
    return rag_sky.rag_summarize(query)


# ---- 工具 9：查询菜品信息 ----
@tool(description="查询苍穹外卖菜品列表。入参keyword为菜品名称关键词(可选)，不传则查询全部菜品")
def sky_query_dish(keyword: str | None = None) -> str:
    """
    查询苍穹外卖菜品信息
    入参：keyword - 菜品名称关键词（可选，不传返回全部菜品列表）
    返回：格式化文本，包含菜品名称、价格、状态
    """
    logger.info(f"[sky_query_dish]查询菜品：keyword={keyword}")
    params = {"page": 1, "pageSize": 20}
    if keyword:
        params["name"] = keyword
    raw = _sky_api_get("/dish/page", params)
    return _sky_format_dishes(raw)


# ---- 工具 10：查询菜品分类 ----
@tool(description="查询苍穹外卖的菜品分类信息。入参type为分类类型(可选)：1=菜品分类 2=套餐分类，不传则查询全部分类")
def sky_query_category(type: int | None = None) -> str:
    """
    查询苍穹外卖菜品分类信息
    入参：type - 分类类型（可选）：1=菜品分类，2=套餐分类，不传返回全部分类
    返回：格式化文本，包含分类名称、类型、状态
    """
    logger.info(f"[sky_query_category]查询分类：type={type}")
    if type is not None:
        raw = _sky_api_get("/category/list", {"type": type})
        return _sky_format_categories(raw, is_list=True)
    raw = _sky_api_get("/category/page", {"page": 1, "pageSize": 20})
    return _sky_format_categories(raw, is_list=False)


# ---- 工具 11：查询套餐信息 ----
@tool(description="查询苍穹外卖的套餐信息。入参keyword为套餐名称关键词(可选)，不传则查询全部套餐列表")
def sky_query_setmeal(keyword: str | None = None) -> str:
    """
    查询苍穹外卖套餐信息
    入参：keyword - 套餐名称关键词（可选，不传返回全部套餐列表）
    返回：格式化文本，包含套餐名称、价格、状态、描述
    """
    logger.info(f"[sky_query_setmeal]查询套餐：keyword={keyword}")
    params = {"page": 1, "pageSize": 20}
    if keyword:
        params["name"] = keyword
    raw = _sky_api_get("/setmeal/page", params)
    return _sky_format_setmeals(raw)


# ---- 工具 12：查询订单信息 ----
@tool(description="查询苍穹外卖的订单信息。入参status为订单状态(可选)：1=待付款 2=待接单 3=已接单 4=配送中 5=已完成 6=已取消，不传查询全部订单")
def sky_query_order(status: int | None = None) -> str:
    """
    查询苍穹外卖订单信息
    入参：status - 订单状态（可选）：1=待付款 2=待接单 3=已接单 4=配送中 5=已完成 6=已取消
    返回：格式化文本，每条订单一行，包含订单号、状态、金额、时间、菜品
    """
    logger.info(f"[sky_query_order]查询订单：status={status}")
    params = {"page": 1, "pageSize": 20}
    if status is not None:
        params["status"] = status
    raw = _sky_api_get("/order/conditionSearch", params)
    return _sky_format_orders(raw)


# ---- 工具 13：生成经营报表 ----
@tool(description="生成苍穹外卖经营数据报表。入参report_type为报表类型：turnover(营业额)/order(订单)/dish(菜品销量top10)/user(用户)，默认turnover。需要入参begin和end为起止日期(格式YYYY-MM-DD)")
def sky_generate_report(report_type: str = "turnover", begin: str | None = None, end: str | None = None) -> str:
    """
    生成苍穹外卖经营数据报表
    入参：report_type - 报表类型：turnover(营业额)/order(订单)/dish(菜品销量top10)/user(用户)
          begin - 开始日期（格式 YYYY-MM-DD，默认最近一年）
          end - 结束日期（格式 YYYY-MM-DD，默认今天）
    返回：格式化文本，包含报表数据摘要
    """
    import datetime
    today = datetime.date.today()
    if end is None:
        end = today.strftime("%Y-%m-%d")
    if begin is None:
        begin = (today - datetime.timedelta(days=365)).strftime("%Y-%m-%d")

    logger.info(f"[sky_generate_report]生成报表：type={report_type}, begin={begin}, end={end}")
    params = {"begin": begin, "end": end}

    endpoint_map = {
        "turnover": "/report/turnoverStatistics",
        "order": "/report/ordersStatistics",
        "dish": "/report/top10",
        "user": "/report/userStatistics",
    }
    endpoint = endpoint_map.get(report_type, "/report/turnoverStatistics")
    raw = _sky_api_get(endpoint, params)
    return _sky_format_report(raw, report_type)
