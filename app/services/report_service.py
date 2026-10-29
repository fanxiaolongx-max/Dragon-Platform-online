# -*- coding: utf-8 -*-
"""报告服务 - 报告的增删改查和渲染"""
import asyncio
import json
from typing import List, Optional, Dict, Any
from app.dao.report_dao import ReportDao, BlockDao, ConfigDao


def _safe_json_loads(value):
    """安全解析 JSON，非法 JSON 返回原字符串而非抛异常。"""
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


class ReportService:
    """报告业务服务"""

    def __init__(self):
        self.report_dao = ReportDao()
        self.block_dao = BlockDao()
        self.config_dao = ConfigDao()

    async def list(self) -> List[dict]:
        """获取报告列表"""
        return await self.report_dao.list_all()

    async def get_detail(self, report_id: int) -> Optional[Dict[str, Any]]:
        """获取报告详情（包含区块和配置）"""
        # 三个查询全部并发，基座 API 往返耗时降为 1 次（而非串行 3 次）
        report, blocks, configs = await asyncio.gather(
            self.report_dao.get(report_id),
            self.block_dao.list_by_report(report_id),
            self.config_dao.list_by_report(report_id),
        )
        if not report:
            return None

        # 解析各区块的透视配置（section='process'），提取多维度字段/度量/自定义名称供前端表格表头/图表展示
        dim_fields_by_block: Dict[int, list] = {}
        dim_labels_by_block: Dict[int, dict] = {}
        metrics_by_block: Dict[int, list] = {}
        for config in configs:
            if config.get("section") != "process" or not config.get("block_id"):
                continue
            try:
                cfg = _safe_json_loads(config.get("config_text")) or {}
                if not isinstance(cfg, dict):
                    continue
                block_id = int(config["block_id"])
                if isinstance(cfg.get("dim_fields"), list) and cfg["dim_fields"]:
                    dim_fields_by_block[block_id] = [str(f) for f in cfg["dim_fields"] if f]
                elif cfg.get("dim_field"):
                    dim_fields_by_block[block_id] = [str(cfg["dim_field"])]
                # 维度自定义名称：dim_labels={field: 显示名}，仅保留非空
                if isinstance(cfg.get("dim_labels"), dict) and cfg["dim_labels"]:
                    dim_labels_by_block[block_id] = {
                        str(k): str(v) for k, v in cfg["dim_labels"].items() if v
                    }
                # 多度量配置：metrics=[{field,agg,label?},...]；回退兼容单度量 metric_field+agg
                if isinstance(cfg.get("metrics"), list) and cfg["metrics"]:
                    metrics_by_block[block_id] = [
                        {
                            "field": str(m["field"]),
                            "agg": str(m.get("agg") or "count"),
                            "label": str(m["label"]) if m.get("label") else None,
                        }
                        for m in cfg["metrics"]
                        if isinstance(m, dict) and m.get("field")
                    ]
                elif cfg.get("metric_field"):
                    metrics_by_block[block_id] = [
                        {
                            "field": str(cfg["metric_field"]),
                            "agg": str(cfg.get("agg") or "count"),
                            "label": None,
                        }
                    ]
            except (TypeError, ValueError):
                continue

        return {
            "id": report["id"],
            "name": report["name"],
            "title": report["title"],
            "description": report.get("description", ""),
            "status": report.get("status", "draft"),
            "header_html": report.get("header_html"),
            "content": report.get("content"),
            "created_at": report.get("created_at"),
            "updated_at": report.get("updated_at"),
            "blocks": [
                {
                    "id": block["id"],
                    "block_key": block.get("block_key", ""),
                    "block_no": block.get("block_no", ""),
                    "block_title": block.get("block_title", ""),
                    "content_html": block.get("content_html"),
                    "data_element_id": block.get("data_element_id"),
                    "chart_type": block.get("chart_type", "none"),
                    "chart_data": _safe_json_loads(block.get("chart_data")),
                    "dim_fields": dim_fields_by_block.get(int(block["id"]), []),
                    "dim_labels": dim_labels_by_block.get(int(block["id"]), {}),
                    "metrics": metrics_by_block.get(int(block["id"]), []),
                    "order_no": block.get("order_no", 0),
                    "created_at": block.get("created_at"),
                    "updated_at": block.get("updated_at"),
                }
                for block in blocks
            ],
            "configs": [
                {
                    "id": config["id"],
                    "block_id": config.get("block_id"),
                    "section": config.get("section", "style"),
                    "config_text": _safe_json_loads(config.get("config_text"))
                }
                for config in configs
            ]
        }

    async def create(self, data: Dict[str, Any]) -> dict:
        """创建报告"""
        return await self.report_dao.create(data)

    async def update(self, report_id: int, data: Dict[str, Any]) -> Optional[dict]:
        """更新报告"""
        report = await self.report_dao.get(report_id)
        if not report:
            return None

        return await self.report_dao.update(report_id, data)

    async def delete(self, report_id: int) -> bool:
        """删除报告"""
        report = await self.report_dao.get(report_id)
        if not report:
            return False

        await self.report_dao.delete(report_id)
        return True

    # ========== 区块管理 ==========

    async def save_blocks(self, report_id: int, blocks_data: List[Dict[str, Any]]) -> List[dict]:
        """保存报告的区块（整体替换）"""
        report = await self.report_dao.get(report_id)
        if not report:
            raise ValueError("报告不存在")

        # 删除现有区块
        await self.block_dao.delete_by_report(report_id)

        # 创建新区块
        saved_blocks = []
        for idx, block_data in enumerate(blocks_data):
            block_data["report_id"] = report_id
            block_data["order_no"] = idx

            # 序列化 JSON 字段
            if "chart_data" in block_data and isinstance(block_data["chart_data"], (dict, list)):
                block_data["chart_data"] = json.dumps(block_data["chart_data"])
            if "title_style" in block_data and isinstance(block_data["title_style"], dict):
                block_data["title_style"] = json.dumps(block_data["title_style"])

            saved_block = await self.block_dao.create(block_data)
            saved_blocks.append(saved_block)

        return saved_blocks

    # ========== 配置管理 ==========

    async def save_config(
        self,
        report_id: int,
        block_id: Optional[int],
        section: str,
        config_data: Dict[str, Any]
    ) -> dict:
        """保存配置（幂等性：相同 block_id + section 则更新，否则创建）"""
        report = await self.report_dao.get(report_id)
        if not report:
            raise ValueError("报告不存在")

        # 查找现有配置
        existing = None
        if block_id is not None:
            configs = await self.config_dao.list_by_block(report_id, block_id)
            for config in configs:
                if config["section"] == section:
                    existing = config
                    break

        # 序列化配置数据
        config_text = json.dumps(config_data) if not isinstance(config_data, str) else config_data

        if existing:
            # 更新现有配置
            return await self.config_dao.update(existing["id"], {"config_text": config_text})
        else:
            # 创建新配置
            return await self.config_dao.create({
                "report_id": report_id,
                "block_id": block_id,
                "section": section,
                "config_text": config_text
            })

    # ========== 渲染 ==========

    async def render(self, report_id: int) -> Optional[Dict[str, Any]]:
        """渲染报告（用于预览和生成）"""
        detail = await self.get_detail(report_id)
        if not detail:
            return None

        # 这里可以添加变量替换逻辑
        # 目前直接返回原始数据
        return detail
