package com.it.pojo;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("health_data")
public class HealthData {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long patientId;

    /** 健康数据，JSON格式，如血压、血糖等 */
    private String dataContent;

    private LocalDateTime createTime;
}
