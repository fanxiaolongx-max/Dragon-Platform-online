-- ============================================================
-- 写报告服务 - 数据库初始化脚本
-- 服务名: platform-write-report
-- 数据库: aiopsdb_dev
-- 字符集: utf8mb4
-- ============================================================

-- 报告模板
CREATE TABLE IF NOT EXISTS `t_report_template` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(128) NOT NULL COMMENT '模板名称',
  `title` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '报告标题',
  `description` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '模板描述',
  `header_html` LONGTEXT NULL COMMENT '报告头富文本(Logo/标题/信息表)',
  `content` LONGTEXT NULL COMMENT '报告结构JSON',
  `status` VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT 'draft/published',
  `created_at` DATETIME DEFAULT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 报告区块
CREATE TABLE IF NOT EXISTS `t_report_block` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `report_id` INT NOT NULL COMMENT '所属报告',
  `block_key` VARCHAR(32) NOT NULL DEFAULT '' COMMENT '区块键',
  `block_no` VARCHAR(16) NOT NULL DEFAULT '' COMMENT '区块编号',
  `block_title` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '区块标题',
  `content_html` LONGTEXT NULL COMMENT '区块内容HTML',
  `data_element_id` INT NULL COMMENT '绑定的数据元素ID',
  `chart_type` VARCHAR(20) NOT NULL DEFAULT 'none' COMMENT '图表类型 none/pie/bar/line',
  `chart_data` LONGTEXT NULL COMMENT '图表数据JSON',
  `order_no` INT NOT NULL DEFAULT 0 COMMENT '排序序号',
  `created_at` DATETIME DEFAULT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_block_report` (`report_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 数据元素
CREATE TABLE IF NOT EXISTS `t_data_element` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `element_key` VARCHAR(64) NOT NULL COMMENT '元素唯一键',
  `name` VARCHAR(128) NOT NULL COMMENT '显示名称',
  `category` VARCHAR(64) NOT NULL DEFAULT '默认' COMMENT '分类',
  `data_kind` VARCHAR(20) NOT NULL DEFAULT 'form' COMMENT 'form=表单/indicator=指标',
  `data_type` VARCHAR(20) NOT NULL DEFAULT 'string' COMMENT 'string/number/date/percent',
  `is_calc` INT NOT NULL DEFAULT 0 COMMENT '是否计算型指标 0/1',
  `data_source_id` INT NULL COMMENT '关联数据来源ID',
  `default_value` VARCHAR(255) NULL COMMENT '默认值',
  `sample_data` TEXT NULL COMMENT '样例数据JSON',
  `description` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '说明',
  `source_db` VARCHAR(64) NOT NULL DEFAULT 'netcare' COMMENT '来源库',
  `source_table` VARCHAR(128) NULL COMMENT '来源表',
  `field_select` TEXT NULL COMMENT '字段选择JSON',
  `time_field` VARCHAR(64) NULL COMMENT '时间字段映射',
  `region_field` VARCHAR(64) NULL COMMENT '地区部字段映射',
  `reoffice_field` VARCHAR(64) NULL COMMENT '代表处字段映射',
  `calc_source` VARCHAR(20) NOT NULL DEFAULT '' COMMENT 'default_set/db_calc',
  `static_ref` VARCHAR(64) NULL COMMENT '默认指标集引用key',
  `created_at` DATETIME DEFAULT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_element_key` (`element_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 数据来源
CREATE TABLE IF NOT EXISTS `t_data_source` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `source_key` VARCHAR(64) NOT NULL COMMENT '来源唯一键',
  `name` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '来源名称',
  `source_type` VARCHAR(20) NOT NULL DEFAULT 'static' COMMENT 'api/db/static',
  `config_text` TEXT NULL COMMENT '来源配置JSON',
  `description` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '说明',
  `created_at` DATETIME DEFAULT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_source_key` (`source_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 报告配置
CREATE TABLE IF NOT EXISTS `t_report_config` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `report_id` INT NOT NULL COMMENT '所属报告',
  `block_id` INT NULL COMMENT '所属区块(0表示报告级)',
  `section` VARCHAR(20) NOT NULL DEFAULT 'style' COMMENT 'header/style/layout/process/data',
  `config_text` LONGTEXT NULL COMMENT '配置内容JSON',
  `created_at` DATETIME DEFAULT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_config_block` (`report_id`, `block_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- ============================================================
-- 初始数据
-- ============================================================

-- 数据来源样例
INSERT INTO `t_data_source` (`source_key`, `name`, `source_type`, `config_text`, `description`)
VALUES
  ('source_base', '月度基础统计', 'static',
   '{"data":{"report_period":"2026年09月","project_name":"埃及代表处交付与服务","project_no":"EGYPT-CS-2026","report_date":"2026-10-05","reportor":"张工","reviewer":"李工"}}',
   '基础信息数据来源'),
  ('source_network', '网络状态统计', 'static',
   '{"data":{"device_online_rate":"98.5%","link_healthy_rate":"99.2%","network_health_score":92,"active_device":128,"total_device":130}}',
   '网络状态数据'),
  ('source_event', '事件与告警统计', 'static',
   '{"data":{"monthly_incident":12,"major_alarm":3,"critical_event":1,"handle_rate":"91.7%"}}',
   '事件与告警数据')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);

-- 数据元素样例
INSERT INTO `t_data_element` (`element_key`, `name`, `category`, `data_kind`, `data_type`, `is_calc`, `default_value`, `description`, `source_db`, `calc_source`, `static_ref`)
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
  ('incident_pie', '事件分布饼图', '图表数据', 'form', 'string', 0, NULL,
   '事件类别分布（饼图）', 'netcare', '', NULL),
  ('device_bar', '设备状态柱状图', '图表数据', 'form', 'string', 0, NULL,
   '设备状态分布（柱状图）', 'netcare', '', NULL),
  ('risk_completion_rate', '中高风险处置完成率', '风险指标', 'percent', 1, NULL,
   '中高风险任务的处置完成率', 'netcare', 'default_set', 'risk_completion_rate')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);
