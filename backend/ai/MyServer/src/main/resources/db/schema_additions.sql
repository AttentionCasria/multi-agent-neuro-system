-- 健康管理系统 补充建表脚本
-- 执行前请确保 medai 数据库已存在，且 patient 和 user 表已创建
-- 注意：patient 表的外键指向 user 表（非 med_user）

USE medai;

-- =====================
-- ai_opinion 表
-- =====================
CREATE TABLE IF NOT EXISTS ai_opinion (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    patient_id    BIGINT UNSIGNED NOT NULL                           COMMENT '病人ID',
    risk_level    VARCHAR(16)                                        COMMENT '风险等级(低/中/高)',
    suggestions   TEXT                                               COMMENT 'AI建议',
    analysis_details TEXT                                           COMMENT '分析详情',
    source_type   VARCHAR(16) DEFAULT 'health_data'                 COMMENT '来源类型(health_data/sync_talk)',
    source_id     BIGINT UNSIGNED                                    COMMENT '来源ID(健康数据ID或talk_id)',
    create_time   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP     COMMENT '创建时间',
    update_time   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                  ON UPDATE CURRENT_TIMESTAMP                        COMMENT '更新时间',
    INDEX idx_patient_id(patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI分析意见表';

-- =====================
-- health_data 表
-- =====================
CREATE TABLE IF NOT EXISTS health_data (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    patient_id    BIGINT UNSIGNED NOT NULL                           COMMENT '病人ID',
    data_content  TEXT            NOT NULL                           COMMENT '健康数据(JSON格式，如血压、血糖等)',
    create_time   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_patient_id(patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='病人健康数据表';

-- =====================
-- learning_material 表
-- =====================
CREATE TABLE IF NOT EXISTS learning_material (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '资料ID',
    title       VARCHAR(128)    NOT NULL                            COMMENT '资料标题',
    category    VARCHAR(64)                                         COMMENT '分类(如心血管疾病)',
    type        VARCHAR(32)                                         COMMENT '类型(文档/视频/链接)',
    url         VARCHAR(512)                                        COMMENT '文件链接',
    content     TEXT                                                COMMENT '详细内容',
    create_time DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP  COMMENT '创建时间',
    update_time DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP                         COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='医生学习资料表';
