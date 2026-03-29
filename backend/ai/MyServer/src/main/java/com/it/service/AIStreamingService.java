package com.it.service;

import com.it.po.uo.ContDTO;
import com.it.po.vo.AnswerVO;
import com.it.pojo.Talk;
import reactor.core.publisher.Flux;
import java.util.List;

public interface AIStreamingService {
    // 创建新对话
    Long createNewTalk(Long userId);

    // 断线重连/获取当前流式缓存
    String getResumeContent(Long userId, Long talkId);

    // 核心流式对话（images 为影像识别图片列表，无图片时传 null 或空列表）
    Flux<String> streamChat(Long userId, Long talkId, String question, String token, List<String> images);

    // 获取历史对话内容，返回含 role/content/images 的 DTO 列表
    List<ContDTO> getPreContent(Long userId, Long talkId);

    Talk getTalkById(Long talkId);
}