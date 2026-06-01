-- 健康管理系统 补充建表脚本
-- 执行前请确保 medai 数据库已存在

USE medai;

-- =====================
-- patient 表
-- =====================
CREATE TABLE IF NOT EXISTS patient (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    name        VARCHAR(64)     NOT NULL                            COMMENT '患者姓名',
    history     TEXT                                                COMMENT '病史',
    notes       TEXT                                                COMMENT '医生备注',
    doctor_id   BIGINT UNSIGNED NOT NULL                            COMMENT '负责医生ID',
    create_time DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP  COMMENT '创建时间',
    update_time DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP                         COMMENT '更新时间',
    INDEX idx_doctor_id(doctor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='患者信息表';

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

-- =====================
-- cont 表图片支持改造
-- 执行顺序：先加列，再修正旧数据 role
-- =====================

-- 1. 加 role 列（区分 user / assistant），默认先全填 user，后面用 UPDATE 修正
ALTER TABLE cont
    ADD COLUMN role   VARCHAR(16)  NOT NULL DEFAULT 'user'    COMMENT '消息角色：user 或 assistant',
    ADD COLUMN images LONGTEXT     NULL                        COMMENT '用户上传图片的 Base64 列表（JSON 数组），仅 user 消息有值';

-- 2. 修正旧数据：按每个 talkId 内的时间顺序，偶数位（第2、4、6...条）标为 assistant
--    因为 cont 表是一问一答交替写入，奇数位是用户问题，偶数位是 AI 回答
UPDATE cont c
JOIN (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY talkId ORDER BY id) AS rn
    FROM cont
) ranked ON c.id = ranked.id
SET c.role = IF(ranked.rn % 2 = 0, 'assistant', 'user');
