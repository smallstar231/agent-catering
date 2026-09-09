# 评估数据集模块
# 功能：加载/保存离线评估用的测试集（JSONL）
# 每条样本：
#   {"query": "用户问题", "reference": "参考答案(可选)", "category": "分类(可选)"}
# 被 run_eval.py 使用

import json
import os
from utils.logger_handler import logger


def sample_dataset() -> list[dict]:
    """返回一组内置示例（苍穹外卖客服场景），供快速试跑评估"""
    return [
        {"query": "怎么下单？", "reference": "选择菜品加入购物车后确认订单并支付即可下单", "category": "faq"},
        {"query": "配送时间一般多久？", "reference": "一般30-45分钟", "category": "faq"},
        {"query": "退款多久到账？", "reference": "审核通过后1-3个工作日", "category": "faq"},
        {"query": "如何申请退款？", "reference": "订单详情页点击申请退款并提交原因", "category": "faq"},
        {"query": "会员有哪些权益？", "reference": "免配送费、专属折扣、积分加倍等", "category": "faq"},
        {"query": "支持哪些支付方式？", "reference": "微信、支付宝、余额", "category": "faq"},
        {"query": "宫保鸡丁是什么菜？", "reference": "经典川菜", "category": "kb"},
        {"query": "恶劣天气正常配送吗？", "reference": "暴雨台风可能延迟或部分暂停", "category": "faq"},
    ]


def save_dataset(samples: list[dict], path: str) -> str:
    """把样本集写成 JSONL 文件；返回绝对路径"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    logger.info(f"[eval]数据集已保存：{path}（{len(samples)} 条）")
    return path


def load_dataset(path: str) -> list[dict]:
    """从 JSONL 读取测试集"""
    samples = []
    if not os.path.exists(path):
        logger.warning(f"[eval]数据集文件不存在：{path}，返回空")
        return samples
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("query"):
                    samples.append(obj)
            except json.JSONDecodeError as e:
                logger.warning(f"[eval]跳过非法行：{line[:60]}... ({e})")
    return samples


if __name__ == '__main__':
    # 直接运行：把示例集存到默认位置，便于首次体验
    _p = save_dataset(sample_dataset(), os.path.join("data", "eval_dataset.jsonl"))
    print("示例集已保存：", _p)
    print("读取到", len(load_dataset(_p)), "条")
