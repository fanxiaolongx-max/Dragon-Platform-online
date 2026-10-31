-- 显式升级部署：AIR 复用既有五表，不新增请求表。
-- 只补齐缺失结构，不重放种子数据，不改写已有报告。
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
