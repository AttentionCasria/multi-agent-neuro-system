package com.it.pojo;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("learning_material")
public class LearningMaterial {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String title;

    /** 分类，如：心血管疾病 */
    private String category;

    /** 类型：文档 / 视频 / 链接 */
    private String type;

    private String url;

    private String content;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
