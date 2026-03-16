package com.it.service.impl;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.it.po.uo.Cont;
import com.it.pojo.Talk;
import com.it.service.AIStreamingService;
import com.it.service.IContService;
import com.it.service.ITalkService;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RRateLimiter;
import org.redisson.api.RSemaphore;
import org.redisson.api.RateIntervalUnit;
import org.redisson.api.RateType;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class AIStreamingServiceImpl implements AIStreamingService {

    private final WebClient webClient;
    private final StringRedisTemplate stringRedisTemplate;
    private final RedissonClient redissonClient;
    private final ITalkService talkService;
    private final IContService contService;
    private final ConversationPersistenceService conversationPersistenceService;

    private final ObjectMapper objectMapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private static final long CACHE_TTL = 1;
    private static final String HISTORY_KEY_PREFIX = "chat:history:";
    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private static final String SEMAPHORE_KEY = "ai:concurrent";
    private static final int SEMAPHORE_PERMITS = 20;
    private static final String DEFAULT_REPORT_MODE = "emergency";
    private static final boolean DEFAULT_SHOW_THINKING = true;

    /** 发送给模型的历史上下文最大字符数，防止超出模型 Token 上限 */
    private static final int MAX_HISTORY_CHARS = 8000;
    /** 流式响应逐块最大等待时间，超时视为模型挂起 */
    private static final Duration CHUNK_TIMEOUT = Duration.ofSeconds(120);

    @PostConstruct
    public void init() {
        try {
            RSemaphore semaphore = redissonClient.getSemaphore(SEMAPHORE_KEY);
            semaphore.trySetPermits(SEMAPHORE_PERMITS);
            log.info("初始化 semaphore 完成: key={}, permits={}", SEMAPHORE_KEY, SEMAPHORE_PERMITS);
        } catch (Exception e) {
            log.warn("初始化 semaphore 失败: {}", e.getMessage(), e);
        }
    }

    @Transactional
    @Override
    public Long createNewTalk(Long userId) {
        LocalDateTime now = LocalDateTime.now();
        Long talkId = IdWorker.getId();
        Talk talk = Talk.builder()
                .id(talkId)
                .userId(userId)
                .title("新对话")
                .content("")
                .createTime(now)
                .updateTime(now)
                .build();

        log.info("准备保存 Talk: {}", talk);

        try {
            boolean saved = talkService.save(talk);
            log.info("talkService.save 返回: {} (talkId={})", saved, talkId);
            if (!saved) {
                throw new RuntimeException("创建新对话失败");
            }
        } catch (Exception e) {
            log.error("保存 Talk 异常: {}", e.getMessage(), e);
            throw e;
        }

        return talkId;
    }

    @Override
    public String getResumeContent(Long userId, Long talkId) {
        String key = buildRedisKey(userId, talkId);
        try {
            List<String> list = stringRedisTemplate.opsForList().range(key, 0, -1);
            if (list == null || list.isEmpty()) {
                log.debug("Redis list 为空或不存在: key={}", key);
                return null;
            }
            log.debug("Redis list 命中: key={}, size={}, sample={}", key, list.size(), list.get(0));
            return String.join("", list);
        } catch (Exception e) {
            log.error("读取 resume content 失败 userId:{} talkId:{} err:{}", userId, talkId, e.getMessage(), e);
            return null;
        }
    }

    @Transactional(readOnly = true)
    @Override
    public List<String> getPreContent(Long userId, Long talkId) {
        return getCachedHistory(userId, talkId).stream()
                .map(Cont::getContent)
                .collect(Collectors.toList());
    }

    private boolean tryAcquire(String key, int rate, int seconds) {
        try {
            RRateLimiter limiter = redissonClient.getRateLimiter(key);
            limiter.trySetRate(RateType.OVERALL, rate, seconds, RateIntervalUnit.SECONDS);
            boolean ok = limiter.tryAcquire();
            log.debug("限流 tryAcquire: key={}, rate={}, seconds={}, result={}", key, rate, seconds, ok);
            return ok;
        } catch (Exception e) {
            log.warn("限流器操作失败: key={}, err={}", key, e.getMessage(), e);
            return false;
        }
    }

    private Long incrWithExpire(String key, long expireSeconds) {
        String script = "local v = redis.call('incr', KEYS[1]); " +
                "if tonumber(v) == 1 then redis.call('expire', KEYS[1], ARGV[1]); end; return v;";
        DefaultRedisScript<Long> redisScript = new DefaultRedisScript<>(script, Long.class);
        try {
            Long v = stringRedisTemplate.execute(redisScript, Collections.singletonList(key), String.valueOf(expireSeconds));
            log.debug("incrWithExpire: key={}, expire={}, value={}", key, expireSeconds, v);
            return v;
        } catch (Exception e) {
            log.error("执行 incrWithExpire 失败: key={}, err={}", key, e.getMessage(), e);
            return null;
        }
    }

    @Override
    public Flux<String> streamChat(Long userId,
                                   Long talkId,
                                   String question,
                                   String token) {

        if (userId == null) {
            return Flux.just(buildError("未登录"));
        }
        if (StrUtil.isBlank(token)) {
            return Flux.just(buildError("缺少登录令牌"));
        }
        if (!allowAICircuit()) {
            return Flux.just(buildError("AI 服务当前不可用，请稍后重试"));
        }

        // ========= 1️⃣ 自动创建对话 =========
        if (talkId != null) {
            Talk existingTalk = talkService.getById(talkId);
            if (existingTalk == null || !userId.equals(existingTalk.getUserId())) {
                log.warn("talkId={} 不存在或不属于 userId={}，自动创建新对话", talkId, userId);
                talkId = createNewTalk(userId);
            }
        } else {
            talkId = createNewTalk(userId);
            log.info("talkId 为 null，自动创建新对话: userId={}", userId);
        }

        final Long finalTalkId = talkId;

        String historyText = buildHistoryContext(userId, finalTalkId);
        final String requestToken = token.trim();
        final String reportMode = DEFAULT_REPORT_MODE;
        final boolean showThinking = DEFAULT_SHOW_THINKING;

        Map<String, Object> request = new HashMap<>();
        request.put("question", question);
        request.put("round", 2);
        request.put("all_info", historyText);
        request.put("token", requestToken);
        request.put("report_mode", reportMode);
        request.put("show_thinking", showThinking);

        StringBuilder fullAnswer = new StringBuilder();
        final String[] generatedTitle = {null};
        final String[] updatedAllInfo = {historyText};

        return webClient.post()
                .uri("/model/get_result")
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.TEXT_PLAIN)
                .bodyValue(request)
                .retrieve()
                .bodyToFlux(String.class)
                // 每个数据块最多等待 CHUNK_TIMEOUT，防止模型中途挂起导致连接永久卡死
                .timeout(CHUNK_TIMEOUT)

                .filter(line -> line != null && !line.trim().isEmpty())
                .map(String::trim)
                .map(line -> line.startsWith("data:")
                        ? line.substring(5).trim()
                        : line)
                .filter(line -> !line.isEmpty())
                .filter(line -> !"[DONE]".equalsIgnoreCase(line))

                .flatMap(line -> parseModelLine(line, finalTalkId, generatedTitle, updatedAllInfo, fullAnswer), 1)

                .concatWith(Mono.fromCallable(() -> {

                    String finalTitle = generatedTitle[0];
                    if (StrUtil.isBlank(finalTitle)) {
                        finalTitle = buildTitleFromQuestion(question);
                        tryUpdateTalkTitle(finalTalkId, finalTitle);
                    }

                    log.info("准备持久化 - question: '{}', answer length: {}, talkId: {}",
                            question, fullAnswer.length(), finalTalkId);

                    if (question != null && !question.trim().isEmpty() && fullAnswer.length() > 0) {
                        conversationPersistenceService.persistConversation(
                                userId,
                                finalTalkId,
                                question,
                                fullAnswer.toString(),
                                "",
                                finalTitle
                        );
                        stringRedisTemplate.delete("chat:history:" + userId + ":" + finalTalkId);
                    }

                    Map<String, Object> done = new HashMap<>();
                    done.put("type", "done");
                    done.put("talkId", finalTalkId.toString());
                    done.put("title", finalTitle);
                    done.put("name", finalTitle);
                    done.put("all_info", updatedAllInfo[0]);

                    return objectMapper.writeValueAsString(done);
                }))

                .onErrorResume(WebClientResponseException.class, e -> {
                    log.error("调用 AI 服务失败: status={}, body={}", e.getStatusCode(), e.getResponseBodyAsString(), e);
                    // 401 说明两端 JWT 密钥不一致，给出明确提示；其余返回通用消息，不暴露内部细节
                    String msg = e.getStatusCode().value() == 401
                            ? "AI 服务认证失败，请检查 AI_JWT_SECRET 配置是否与后端 AI_API_SHARED_JWT_SECRET 一致"
                            : "AI 服务暂时不可用，请稍后重试";
                    return buildErrorAndDone(finalTalkId, msg);
                })
                .onErrorResume(e -> {
                    boolean isTimeout = e instanceof TimeoutException
                            || (e.getCause() instanceof TimeoutException);
                    if (isTimeout) {
                        log.warn("AI 流式响应超时（{}s 内无数据块）: talkId={}", CHUNK_TIMEOUT.getSeconds(), finalTalkId);
                        return buildErrorAndDone(finalTalkId, "AI 响应超时，请稍后重试");
                    }
                    log.error("流式生成异常", e);
                    return buildErrorAndDone(finalTalkId, "AI 服务异常，请稍后重试");
                })

                .doFinally(signal -> log.info("流完成: signal={}", signal));
    }

    private Flux<String> parseModelLine(String line,
                                        Long talkId,
                                        String[] generatedTitle,
                                        String[] updatedAllInfo,
                                        StringBuilder fullAnswer) {
        try {
            JsonNode json = objectMapper.readTree(line);
            String type = json.path("type").asText("");

            // done 事件：提取 name/all_info 后结束流
            if ("done".equalsIgnoreCase(type)) {
                String name = json.path("name").asText("");
                if (StrUtil.isNotBlank(name)) {
                    generatedTitle[0] = name;
                    tryUpdateTalkTitle(talkId, name);
                }
                String allInfo = json.path("all_info").asText(
                        json.path("summary").asText(""));
                if (StrUtil.isNotBlank(allInfo)) {
                    updatedAllInfo[0] = allInfo;
                }
                return Flux.empty();
            }

            // error 事件
            if ("error".equalsIgnoreCase(type)) {
                String msg = json.path("content").asText("AI服务异常");
                return Flux.just(buildError(msg, talkId));
            }

            // meta 事件：提取 all_info_update 中的汇总信息，透传给前端
            if ("meta".equalsIgnoreCase(type)) {
                JsonNode content = json.path("content");
                // 提取 all_info_update 中的 all_info 和 name
                JsonNode allInfoUpdate = content.path("all_info_update");
                if (!allInfoUpdate.isMissingNode()) {
                    String allInfo = allInfoUpdate.path("all_info").asText("");
                    if (StrUtil.isNotBlank(allInfo)) {
                        updatedAllInfo[0] = allInfo;
                    }
                    String name = allInfoUpdate.path("name").asText("");
                    if (StrUtil.isNotBlank(name)) {
                        generatedTitle[0] = name;
                        tryUpdateTalkTitle(talkId, name);
                    }
                }
                Map<String, Object> metaResp = baseResponse(talkId, generatedTitle[0], "meta");
                metaResp.put("meta", objectMapper.convertValue(content, new TypeReference<Map<String, Object>>() {}));
                return Flux.just(objectMapper.writeValueAsString(metaResp));
            }

            // thinking 事件
            if ("thinking".equalsIgnoreCase(type)) {
                Map<String, Object> thinkingData = new HashMap<>();
                thinkingData.put("step", json.path("step").asText(""));
                thinkingData.put("title", json.path("title").asText(""));
                thinkingData.put("content", json.path("content").asText(""));
                Map<String, Object> thinkingResp = baseResponse(talkId, generatedTitle[0], "thinking");
                thinkingResp.put("thinking", thinkingData);
                return Flux.just(objectMapper.writeValueAsString(thinkingResp));
            }

            // result 事件：追加到完整答案，透传内容给前端
            if ("result".equalsIgnoreCase(type)) {
                String chunk = json.path("content").asText("");
                fullAnswer.append(chunk);
                Map<String, Object> chunkResp = baseResponse(talkId, generatedTitle[0], "chunk");
                chunkResp.put("content", chunk);
                return Flux.just(objectMapper.writeValueAsString(chunkResp));
            }

            return Flux.empty();

        } catch (Exception e) {
            log.error("解析AI返回失败, line={}", line, e);
            return Flux.empty();
        }
    }

    private Map<String, Object> baseResponse(Long talkId, String title, String type) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("type", type);
        payload.put("talkId", talkId.toString());
        payload.put("title", title);
        payload.put("name", title);
        return payload;
    }

    private Flux<String> buildErrorAndDone(Long talkId, String message) {
        try {
            Map<String, Object> error = new HashMap<>();
            error.put("type", "error");
            error.put("talkId", talkId.toString());
            error.put("message", message);

            Map<String, Object> done = new HashMap<>();
            done.put("type", "done");
            done.put("talkId", talkId.toString());
            done.put("title", "异常结束");
            done.put("name", "异常结束");

            return Flux.just(
                    objectMapper.writeValueAsString(error),
                    objectMapper.writeValueAsString(done)
            );
        } catch (Exception ex) {
            return Flux.just("{\"type\":\"done\"}");
        }
    }

    private String buildError(String msg) {
        return buildError(msg, null);
    }

    private String buildError(String msg, Long talkId) {
        try {
            Map<String, Object> err = new HashMap<>();
            err.put("type", "error");
            err.put("message", msg);
            if (talkId != null) {
                err.put("talkId", talkId.toString());
            }
            return objectMapper.writeValueAsString(err);
        } catch (Exception e) {
            return "{\"type\":\"error\",\"message\":\"系统错误\"}";
        }
    }

    @Override
    public Talk getTalkById(Long talkId) {
        if (talkId == null) return null;
        return talkService.getById(talkId);
    }

    @Transactional
    public void tryUpdateTalkTitle(Long talkId, String title) {
        if (talkId == null) return;
        if (title == null || title.trim().isEmpty()) return;

        try {
            Talk talk = talkService.getById(talkId);
            if (talk == null) return;

            // 只在还是“新对话”时更新，避免覆盖用户修改的标题
            if ("新对话".equals(talk.getTitle())) {
                talk.setTitle(title.trim());
                talkService.updateById(talk);
            }
        } catch (Exception e) {
            log.warn("更新对话标题失败: talkId={}, err={}", talkId, e.getMessage(), e);
        }
    }

    private String buildTitleFromQuestion(String question) {
        if (question == null) return "咨询";
        String t = question.trim().replaceAll("\\s+", " ");
        if (t.isEmpty()) return "咨询";
        return t.substring(0, Math.min(t.length(), 12));
    }

    private String buildHistoryContext(Long userId, Long talkId) {
        List<Cont> history = getCachedHistory(userId, talkId);
        if (history == null || history.isEmpty()) return "";

        if (history.size() % 2 != 0) {
            log.warn("历史记录数量为奇数 ({})，丢弃末尾孤立条目以保持角色对齐: userId={}, talkId={}",
                    history.size(), userId, talkId);
            history = history.subList(0, history.size() - 1);
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < history.size(); i++) {
            sb.append(i % 2 == 0 ? "user: " : "assistant: ")
                    .append(history.get(i).getContent()).append("\n");
        }
        String result = sb.toString();

        // 超出上限时从头部截断，保留最近的对话轮次，避免超过模型 Token 上限
        if (result.length() > MAX_HISTORY_CHARS) {
            result = result.substring(result.length() - MAX_HISTORY_CHARS);
            // 截到第一个完整行，避免从行中间截断
            int firstNewline = result.indexOf('\n');
            if (firstNewline >= 0 && firstNewline < result.length() - 1) {
                result = result.substring(firstNewline + 1);
            }
            log.warn("历史上下文超过 {} 字符限制已截断: userId={}, talkId={}", MAX_HISTORY_CHARS, userId, talkId);
        }
        return result;
    }

    private boolean allowAICircuit() {
        String state = stringRedisTemplate.opsForValue().get("ai:circuit");
        log.debug("检查熔断开关状态: {}", state);
        return !"open".equals(state);
    }

    private List<Cont> getCachedHistory(Long userId, Long talkId) {
        String key = buildHistoryKey(userId, talkId);
        String json = stringRedisTemplate.opsForValue().get(key);

        if (json != null && !json.isEmpty()) {
            try {
                List<Cont> cached = objectMapper.readValue(json, new TypeReference<>() {});
                log.debug("历史缓存命中: key={}, size={}", key, cached == null ? 0 : cached.size());
                return cached;
            } catch (Exception e) {
                log.error("解析历史记录缓存失败，将降级查询数据库", e);
            }
        } else {
            log.debug("历史缓存未命中: key={}", key);
        }

        return reloadHistoryToCache(userId, talkId);
    }

    private List<Cont> reloadHistoryToCache(Long userId, Long talkId) {
        List<Cont> history = contService.list(
                new LambdaQueryWrapper<Cont>()
                        .eq(Cont::getUserId, userId)
                        .eq(Cont::getTalkId, talkId)
                        .orderByAsc(Cont::getId)
        );

        log.debug("从 DB 加载历史记录: userId={}, talkId={}, size={}", userId, talkId, history == null ? 0 : history.size());

        try {
            String key = buildHistoryKey(userId, talkId);
            // 先删除旧缓存，再设置新缓存
            stringRedisTemplate.delete(key);
            stringRedisTemplate.opsForValue().set(key, objectMapper.writeValueAsString(history), 1, TimeUnit.HOURS);
            log.debug("历史记录已写入缓存: key={}", key);
        } catch (Exception e) {
            log.error("写入历史记录缓存失败", e);
        }

        return history;
    }

    private String buildRedisKey(Long userId, Long talkId) {
        return "chat:stream:" + userId + ":" + talkId;
    }

    private String buildHistoryKey(Long userId, Long talkId) {
        return HISTORY_KEY_PREFIX + userId + ":" + talkId;
    }
}
