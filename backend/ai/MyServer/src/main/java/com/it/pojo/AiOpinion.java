package com.it.pojo;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("ai_opinion")
public class AiOpinion {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long patientId;

    /** 风险等级：低 / 中 / 高 */
    private String riskLevel;

    /** AI建议（纯文本或JSON数组字符串） */
    private String suggestions;

    private String analysisDetails;

    /** 来源类型：health_data / sync_talk */
    private String sourceType;

    /** 来源ID：健康数据ID 或 talk_id */
    private Long sourceId;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
