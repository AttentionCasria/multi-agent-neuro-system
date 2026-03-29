package com.it.po.uo;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 历史消息返回前端的数据结构。
 * role: "user" 或 "assistant"
 * content: 消息文本
 * images: 用户上传图片的 Base64 列表，assistant 消息为空列表
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class ContDTO {

    private String role;
    private String content;
    private List<String> images;
}
