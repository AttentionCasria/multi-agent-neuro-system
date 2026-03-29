package com.it.po.uo;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@TableName("cont")
public class Cont {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;
    private Long talkId;

    private String content;

    /** 消息角色：user 或 assistant */
    private String role;

    /** 用户上传图片的 Base64 列表，序列化为 JSON 字符串存储，assistant 消息为 null */
    private String images;

    private LocalDateTime createTime;
}