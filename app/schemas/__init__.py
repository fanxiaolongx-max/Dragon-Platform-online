# -*- coding: utf-8 -*-
"""Pydantic 模型 -- 请求/响应校验"""

from pydantic import BaseModel, ConfigDict, field_serializer
from typing import Optional, List, Any
from datetime import datetime
import json


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """统一日期时间格式为 YYYY-MM-DD HH:MM:SS"""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# 自定义字段：接受 str/list/dict，序列化为 JSON 字符串存储
def _coerce_to_str(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


# ============================================================
# ReportTemplate
# ============================================================

class ReportTemplateCreate(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    header_html: Optional[str] = None
    content: Optional[str] = None
    status: str = "draft"


class ReportTemplateUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    header_html: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None


class ReportTemplateOut(ReportTemplateCreate):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return _format_datetime(dt)


# ============================================================
# Block
# ============================================================

class BlockIn(BaseModel):
    id: Optional[int] = None
    block_key: str = ""
    block_no: str = ""
    block_title: str = ""
    content_html: Optional[str] = None
    data_element_id: Optional[int] = None
    chart_type: str = "none"
    chart_data: Optional[Any] = None
    order_no: int = 0

    model_config = ConfigDict(
        json_encoders={},
    )

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        # chart_data 如果是 list/dict，序列化为 JSON 字符串
        if d.get("chart_data") is not None and not isinstance(d["chart_data"], str):
            d["chart_data"] = json.dumps(d["chart_data"], ensure_ascii=False)
        return d


class BlockOut(BlockIn):
    id: int
    report_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return _format_datetime(dt)


# ============================================================
# DataElement
# ============================================================

class DataElementCreate(BaseModel):
    element_key: str
    name: str
    category: str = "默认"
    data_kind: str = "form"
    data_type: str = "string"
    is_calc: int = 0
    data_source_id: Optional[int] = None
    default_value: Optional[str] = None
    sample_data: Optional[str] = None
    description: str = ""
    source_db: str = "netcare"
    source_table: Optional[str] = None
    field_select: Optional[str] = None
    time_field: Optional[str] = None
    region_field: Optional[str] = None
    reoffice_field: Optional[str] = None
    calc_source: str = ""
    static_ref: Optional[str] = None


class DataElementUpdate(BaseModel):
    element_key: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    data_kind: Optional[str] = None
    data_type: Optional[str] = None
    is_calc: Optional[int] = None
    data_source_id: Optional[int] = None
    default_value: Optional[str] = None
    sample_data: Optional[str] = None
    description: Optional[str] = None
    source_db: Optional[str] = None
    source_table: Optional[str] = None
    field_select: Optional[str] = None
    time_field: Optional[str] = None
    region_field: Optional[str] = None
    reoffice_field: Optional[str] = None
    calc_source: Optional[str] = None
    static_ref: Optional[str] = None


class DataElementOut(DataElementCreate):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return _format_datetime(dt)


# ============================================================
# DataSource
# ============================================================

class DataSourceCreate(BaseModel):
    source_key: str
    name: str = ""
    source_type: str = "static"
    config_text: Optional[str] = None
    description: str = ""


class DataSourceUpdate(BaseModel):
    source_key: Optional[str] = None
    name: Optional[str] = None
    source_type: Optional[str] = None
    config_text: Optional[str] = None
    description: Optional[str] = None


class DataSourceOut(DataSourceCreate):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return _format_datetime(dt)


# ============================================================
# ReportConfig
# ============================================================

class ReportConfigIn(BaseModel):
    block_id: Optional[int] = None
    section: str = "style"
    config_text: Optional[str] = None


class ReportConfigOut(ReportConfigIn):
    id: int
    report_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# Risk / Pivot
# ============================================================

class RiskCompletionRateOut(BaseModel):
    region_code: str
    region_name: str
    repoffice_code: str
    repoffice_name: str
    total: int
    closed: int
    completion_rate: float
