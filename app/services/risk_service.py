# -*- coding: utf-8 -*-
"""风险指标统计服务：中高风险处置完成率。

算法（依据需求约定）：
    完成率 = 状态为 Closed（已关闭/已闭环）的条目数 / 总条目数 * 100，保留两位小数。
统计对象：业务只读库(netcare)下的 OP_IOC_RISK_TASK_DTL_D_DWD 表。
筛选条件：按报表头选择的地区部编码(REGION_CODE)与代表处编码(REPOFFICE_CODE)。
"""
from app.db import query_business
from app.core.exceptions import DataSourceError

# 完成状态判定：数据字典中代表"已处置完成/已关闭/已闭环"的状态
CLOSED_STATUSES = ("Risk Closed", "已闭环")

# 统计目标表（业务只读库 netcare）
DWD_TABLE = "op_ioc_risk_task_dtl_d_dwd"

# 地区部/代表处 编码 -> 中文名称
REGION_NAME_MAP = {"027425": "中国地区部"}
REPOFFICE_NAME_MAP = {"028188": "浙江代表处"}


class RiskService:
    """风险指标统计服务（使用业务只读库）。"""

    async def get_completion_rate(self, region_code: str, repoffice_code: str) -> dict:
        """统计指定地区部+代表处的中高风险处置完成率。

        Args:
            region_code: 地区部编码，如 027425
            repoffice_code: 代表处编码，如 028188

        Returns:
            dict: 含 total/closed/completion_rate(保留两位小数百分数) 及各编码/名称
        """
        try:
            # 总条目数
            total_sql = (
                f"SELECT COUNT(*) as cnt FROM {DWD_TABLE} "
                f"WHERE REGION_CODE = '{region_code}' AND REPOFFICE_CODE = '{repoffice_code}'"
            )
            total_rows = await query_business(total_sql)
            total = total_rows[0]["cnt"] if total_rows else 0

            # Closed(已完成) 条目数
            status_list = ", ".join([f"'{s}'" for s in CLOSED_STATUSES])
            closed_sql = (
                f"SELECT COUNT(*) as cnt FROM {DWD_TABLE} "
                f"WHERE REGION_CODE = '{region_code}' AND REPOFFICE_CODE = '{repoffice_code}' "
                f"AND RISK_STATUS IN ({status_list})"
            )
            closed_rows = await query_business(closed_sql)
            closed = closed_rows[0]["cnt"] if closed_rows else 0
        except Exception as e:
            raise DataSourceError(message=f"统计风险完成率失败: {e}") from e

        rate = round(closed / total * 100, 2) if total else 0.0
        return {
            "region_code": region_code,
            "region_name": REGION_NAME_MAP.get(region_code, ""),
            "repoffice_code": repoffice_code,
            "repoffice_name": REPOFFICE_NAME_MAP.get(repoffice_code, ""),
            "total": total,
            "closed": closed,
            "completion_rate": rate,
        }
