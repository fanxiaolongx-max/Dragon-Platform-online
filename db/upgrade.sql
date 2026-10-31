-- 显式升级部署：AIR 复用既有五表，不新增请求表。
-- 只补齐缺失结构，不重放种子数据，不改写已有报告。
-- ============================================================
-- 写报告服务 - 数据库初始化脚本
-- 服务名: platform-write-report
-- 目标库: 基座分配的 APP_SCHEMA（应用 UUID），不得在业务库执行
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
