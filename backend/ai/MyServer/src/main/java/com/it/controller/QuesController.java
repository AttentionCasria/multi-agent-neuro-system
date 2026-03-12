package com.it.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.it.po.uo.QuesParam;
import com.it.pojo.Result;
import com.it.pojo.Talk;
import com.it.service.AIStreamingService;
import com.it.utils.ThreadLocalUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@CrossOrigin("*")
@RequestMapping("/api/user/ques")
@RequiredArgsConstructor
public class QuesController {

    private final AIStreamingService streamingService;
    private final ObjectMapper objectMapper;

    @GetMapping("/getQues/{talk_id}")
    public Result getPreContent(@PathVariable("talk_id") String talkIdStr) {
        Long talkId = Long.parseLong(talkIdStr);
        log.info("收到对话内容请求: talkId={}", talkId);  // 添加这行
        if (talkId == null || talkId <= 0) {
            return Result.success(List.of());
        }
        if (ThreadLocalUtil.getCurrentUser() == null) {
            return Result.error("未登录");
        }
        Long userId = ThreadLocalUtil.getCurrentUser().getId();
        return Result.success(streamingService.getPreContent(userId, talkId));
    }

    @PostMapping(value = "/streamingQues", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> streamingQues(
            @RequestBody QuesParam quesParam,
            @RequestHeader(value = "token", required = false) String token,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        if (ThreadLocalUtil.getCurrentUser() == null) {
            return Flux.just(sse("error", json("error", mapOf("message", "未登录"))));
        }

        String upstreamToken = resolveToken(token, authorization);

        Long userId = ThreadLocalUtil.getCurrentUser().getId();
        String talkIdStr = quesParam.getTalkId();
        Long talkId = null;

        if (talkIdStr != null && !talkIdStr.isBlank()) {
            try {
                talkId = Long.parseLong(talkIdStr);
                if (talkId != null && talkId <= 0) {
                    talkId = null;
                }
            } catch (NumberFormatException e) {
                talkId = null; // 非法 talkId 当作新对话处理
            }
        }

        boolean needCreate = (talkId == null || talkId <= 0);

        if (!needCreate) {
            Talk dbTalk = streamingService.getTalkById(talkId);
            if (dbTalk == null || !dbTalk.getUserId().equals(userId)) {
                needCreate = true;
            }
        }

        if (needCreate) {
            talkId = streamingService.createNewTalk(userId);
            log.info("创建新对话 talkId = {}", talkId);
        }

        final Long finalTalkId = talkId;
        final boolean finalNeedCreate = needCreate;

        // ===== 统一 JSON 协议 =====

        Flux<String> initFlux = Flux.just(
                json("init", mapOf(
                        "talkId", finalTalkId.toString(),
                        "newTalk", finalNeedCreate
                ))
        );

        Flux<String> resumeFlux = Flux.defer(() -> {
            String resume = streamingService.getResumeContent(userId, finalTalkId);
            if (resume == null || resume.isBlank()) {
                return Flux.empty();
            }
            return Mono.fromCallable(() -> json("resume", mapOf(
                    "talkId", finalTalkId.toString(),
                    "content", resume
            ))).flux();
        });

        Flux<String> chatFlux = streamingService
                .streamChat(userId, finalTalkId, quesParam.getQuestion(), upstreamToken)
                .map(this::wrapChunkIfNeeded);

        return initFlux
                .concatWith(resumeFlux)
                .concatWith(chatFlux)
                .onErrorResume(e -> Flux.just(
                        json("error", mapOf(
                                "talkId", finalTalkId.toString(),
                                "message", e.getMessage() == null ? "stream error" : e.getMessage()
                        )),
                        json("done", mapOf(
                                "talkId", finalTalkId.toString(),
                                "title", "异常结束"
                        ))
                ))
                .map(data -> sse(resolveEventName(data), data));

    }

    private ServerSentEvent<String> sse(String event, String data) {
        return ServerSentEvent.<String>builder()
                .event(event)
                .data(data)
                .build();
    }

    private String resolveEventName(String data) {
        if (data == null || data.isBlank()) {
            return "message";
        }
        try {
            return objectMapper.readTree(data).path("type").asText("message");
        } catch (Exception e) {
            return "message";
        }
    }

    private String wrapChunkIfNeeded(String data) {
        if (data == null) {
            return json("chunk", mapOf("content", ""));
        }
        String trimmed = data.trim();
        if (!trimmed.isEmpty() && trimmed.startsWith("{") && trimmed.endsWith("}")) {
            return data;
        }
        return json("chunk", mapOf("content", data));
    }

    private String resolveToken(String token, String authorization) {
        if (token != null && !token.isBlank()) {
            return token.trim();
        }
        if (authorization != null && !authorization.isBlank()) {
            String value = authorization.trim();
            return value.startsWith("Bearer ") ? value.substring(7).trim() : value;
        }
        return null;
    }

    private String json(String type, Map<String, Object> payload) {
        try {
            Map<String, Object> root = new HashMap<>();
            root.put("type", type);
            if (payload != null && !payload.isEmpty()) {
                root.putAll(payload);
            }
            return objectMapper.writeValueAsString(root);
        } catch (Exception e) {
            return "{\"type\":\"error\",\"message\":\"json serialize error\"}";
        }
    }

    private Map<String, Object> mapOf(Object k1, Object v1) {
        Map<String, Object> m = new HashMap<>();
        m.put(String.valueOf(k1), v1);
        return m;
    }

    private Map<String, Object> mapOf(Object k1, Object v1, Object k2, Object v2) {
        Map<String, Object> m = new HashMap<>();
        m.put(String.valueOf(k1), v1);
        m.put(String.valueOf(k2), v2);
        return m;
    }
}
