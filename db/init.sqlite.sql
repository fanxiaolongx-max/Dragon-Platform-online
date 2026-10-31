-- ============================================================
-- 写报告服务 - SQLite 兼容数据库初始化脚本
-- 服务名: platform-write-report / AiOps-Report
-- 适配环境: tools-platform 托管应用专属应用库 (app.db)
-- ============================================================

-- 报告模板
CREATE TABLE IF NOT EXISTS t_report_template (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  header_html TEXT,
  content TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at DATETIME DEFAULT NULL,
  updated_at DATETIME DEFAULT NULL
);

-- 报告区块
CREATE TABLE IF NOT EXISTS t_report_block (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER NOT NULL,
  block_key TEXT NOT NULL DEFAULT '',
  block_no TEXT NOT NULL DEFAULT '',
  block_title TEXT NOT NULL DEFAULT '',
  content_html TEXT,
  data_element_id INTEGER,
  chart_type TEXT NOT NULL DEFAULT 'none',
  chart_data TEXT,
  order_no INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME DEFAULT NULL,
  updated_at DATETIME DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_block_report ON t_report_block(report_id);

-- 数据元素
CREATE TABLE IF NOT EXISTS t_data_element (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  element_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '默认',
  data_kind TEXT NOT NULL DEFAULT 'form',
  data_type TEXT NOT NULL DEFAULT 'string',
  is_calc INTEGER NOT NULL DEFAULT 0,
  data_source_id INTEGER,
  default_value TEXT,
  sample_data TEXT,
  description TEXT NOT NULL DEFAULT '',
  source_db TEXT NOT NULL DEFAULT 'netcare',
  source_table TEXT,
  field_select TEXT,
  time_field TEXT,
  region_field TEXT,
  reoffice_field TEXT,
  calc_source TEXT NOT NULL DEFAULT '',
  static_ref TEXT,
  created_at DATETIME DEFAULT NULL,
  updated_at DATETIME DEFAULT NULL
);

-- 数据来源
CREATE TABLE IF NOT EXISTS t_data_source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL DEFAULT 'static',
  config_text TEXT,
  description TEXT NOT NULL DEFAULT '',
  created_at DATETIME DEFAULT NULL,
  updated_at DATETIME DEFAULT NULL
);

-- 报告配置
CREATE TABLE IF NOT EXISTS t_report_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER NOT NULL,
  block_id INTEGER,
  section TEXT NOT NULL DEFAULT 'style',
  config_text TEXT,
  created_at DATETIME DEFAULT NULL,
  updated_at DATETIME DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_config_block ON t_report_config(report_id, block_id);

-- ============================================================
-- 初始种子数据
-- ============================================================

-- 数据来源样例
INSERT OR IGNORE INTO t_data_source (source_key, name, source_type, config_text, description)
VALUES
  ('source_base', '月度基础统计', 'static',
   '{"data":{"report_period":"2026年09月","project_name":"埃及代表处交付与服务","project_no":"EGYPT-CS-2026","report_date":"2026-10-05","reportor":"张工","reviewer":"李工"}}',
   '基础信息数据来源'),
  ('source_network', '网络状态统计', 'static',
   '{"data":{"device_online_rate":"98.5%","link_healthy_rate":"99.2%","network_health_score":92,"active_device":128,"total_device":130}}',
   '网络状态数据'),
  ('source_event', '事件与告警统计', 'static',
   '{"data":{"monthly_incident":12,"major_alarm":3,"critical_event":1,"handle_rate":"91.7%"}}',
   '事件与告警数据');

-- 数据元素样例
INSERT OR IGNORE INTO t_data_element (element_key, name, category, data_kind, data_type, is_calc, default_value, description, source_db, calc_source, static_ref)
VALUES
  ('report_period', '报告周期', '基础信息', 'form', 'string', 0, '2026年09月', '报告统计周期', 'netcare', '', NULL),
  ('project_name', '项目名称', '基础信息', 'form', 'string', 0, '埃及代表处交付与服务', '项目名称', 'netcare', '', NULL),
  ('project_no', '项目编号', '基础信息', 'form', 'string', 0, 'EGYPT-CS-2026', '项目编号', 'netcare', '', NULL),
  ('report_date', '报告日期', '基础信息', 'form', 'date', 0, '2026-10-05', '生成日期', 'netcare', '', NULL),
  ('reportor', '报告人', '基础信息', 'form', 'string', 0, '张工', '报告人', 'netcare', '', NULL),
  ('reviewer', '审核人', '基础信息', 'form', 'string', 0, '李工', '审核人', 'netcare', '', NULL),
  ('device_online_rate', '设备在线率', '网络状态', 'form', 'percent', 0, '98.5%', '设备在线率', 'netcare', '', NULL),
  ('link_healthy_rate', '链路健康率', '网络状态', 'form', 'percent', 0, '99.2%', '链路健康率', 'netcare', '', NULL),
  ('network_health_score', '网络健康分', '网络状态', 'form', 'number', 0, '92', '网络健康评分', 'netcare', '', NULL),
  ('active_device', '在线设备数', '网络状态', 'form', 'number', 0, '128', '在线设备数量', 'netcare', '', NULL),
  ('total_device', '设备总数', '网络状态', 'form', 'number', 0, '130', '设备总数', 'netcare', '', NULL),
  ('monthly_incident', '本月事件数', '事件与告警', 'form', 'number', 0, '12', '本月事件数量', 'netcare', '', NULL),
  ('major_alarm', '重大告警数', '事件与告警', 'form', 'number', 0, '3', '重大告警数量', 'netcare', '', NULL),
  ('critical_event', '重大事件数', '事件与告警', 'form', 'number', 0, '1', '重大事件数量', 'netcare', '', NULL),
  ('handle_rate', '事件处理率', '事件与告警', 'form', 'percent', 0, '91.7%', '事件处理完成率', 'netcare', '', NULL),
  ('incident_pie', '事件分布饼图', '图表数据', 'form', 'string', 0, NULL, '事件类别分布（饼图）', 'netcare', '', NULL),
  ('device_bar', '设备状态柱状图', '图表数据', 'form', 'string', 0, NULL, '设备状态分布（柱状图）', 'netcare', '', NULL),
  ('risk_completion_rate', '中高风险处置完成率', '风险指标', 'indicator', 'percent', 1, NULL, '中高风险任务的处置完成率', 'netcare', 'default_set', 'risk_completion_rate');
