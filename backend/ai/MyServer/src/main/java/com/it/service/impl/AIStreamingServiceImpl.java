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
import com.it.po.uo.ContDTO;
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
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.util.concurrent.ConcurrentLinkedQueue;
import org.springframework.scheduling.annotation.Scheduled;
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
    /** 单行 SSE 数据最大字符数（1 MB），超过此限制的行将被截断并发送 warning 事件 */
    private static final int MAX_LINE_LENGTH = 1_048_576;
    /** 单个持久化任务最大重试次数，超过后永久丢弃（可接入告警） */
    private static final int MAX_PERSIST_RETRIES = 3;

    /**
     * 持久化失败重试任务，记录一次对话的完整上下文及当前重试次数。
     * 应用重启后队列清空，生产环境可替换为 Redis Stream 实现跨实例持久化。
     */
    private record PersistenceTask(
            Long userId,
            Long talkId,
            String question,
            String answer,
            String title,
            List<String> images,
            int retryCount) {}

    /** 持久化失败重试队列（内存级，线程安全） */
    private final ConcurrentLinkedQueue<PersistenceTask> retryQueue = new ConcurrentLinkedQueue<>();

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
    public List<ContDTO> getPreContent(Long userId, Long talkId) {
        // 直接查数据库，不走 Redis 缓存
        // 原因：Redis 缓存中 images 字段已被剔除（避免大字段膨胀），
        //       前端加载历史记录时需要完整的图片数据，必须从 DB 取
        List<Cont> history = contService.list(
                new LambdaQueryWrapper<Cont>()
                        .eq(Cont::getUserId, userId)
                        .eq(Cont::getTalkId, talkId)
                        .orderByAsc(Cont::getId)
        );
        if (history == null) return Collections.emptyList();

        return history.stream()
                .map(cont -> {
                    // 将 images JSON 字符串反序列化回 List<String>，失败时降级为空列表
                    List<String> imageList = Collections.emptyList();
                    if (cont.getImages() != null && !cont.getImages().isEmpty()) {
                        try {
                            imageList = objectMapper.readValue(cont.getImages(), new TypeReference<>() {});
                        } catch (Exception e) {
                            log.warn("图片列表反序列化失败，降级为空列表: contId={}", cont.getId());
                        }
                    }
                    return ContDTO.builder()
                            .role(cont.getRole() != null ? cont.getRole() : "user")
                            .content(cont.getContent() != null ? cont.getContent() : "")
                            .images(imageList)
                            .build();
                })
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
                                   String token,
                                   List<String> images) {

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

        // 图片校验：最多 3 张，单张 Base64 解码后不超过 10MB
        if (images != null && !images.isEmpty()) {
            if (images.size() > 3) {
                return Flux.just(buildError("最多上传 3 张图片"));
            }
            for (String img : images) {
                try {
                    String raw = img.contains(",") ? img.split(",", 2)[1] : img;
                    byte[] bytes = java.util.Base64.getDecoder().decode(raw);
                    if (bytes.length > 10 * 1024 * 1024) {
                        return Flux.just(buildError("单张图片不得超过 10MB"));
                    }
                } catch (Exception e) {
                    return Flux.just(buildError("图片格式非法，请使用 Base64 编码"));
                }
            }
        }

        Map<String, Object> request = new HashMap<>();
        request.put("question", question);
        request.put("round", 2);
        request.put("all_info", historyText);
        request.put("token", requestToken);
        request.put("report_mode", reportMode);
        request.put("show_thinking", showThinking);
        // 影像识别：有图片时传入 images 列表，Python 层据此走 vision 分支
        if (images != null && !images.isEmpty()) {
            request.put("images", images);
        }

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
                    // 仅做标题解析（轻量同步），done 事件构造后立即发往前端
                    // 持久化已解耦到 doOnNext 中异步执行，不再阻塞连接释放
                    String finalTitle = generatedTitle[0];
                    if (StrUtil.isBlank(finalTitle)) {
                        finalTitle = buildTitleFromQuestion(question);
                        tryUpdateTalkTitle(finalTalkId, finalTitle);
                    }

                    Map<String, Object> done = new HashMap<>();
                    done.put("type", "done");
                    done.put("talkId", finalTalkId.toString());
                    done.put("title", finalTitle);
                    done.put("name", finalTitle);
                    done.put("all_info", updatedAllInfo[0]);

                    return objectMapper.writeValueAsString(done);
                }))

                // done 事件先发给前端，doOnNext 随即在 boundedElastic 线程池中异步持久化
                // 即使持久化失败，SSE 流也已正常关闭，不影响用户侧体验
                .doOnNext(eventJson -> {
                    try {
                        JsonNode node = objectMapper.readTree(eventJson);
                        if (!"done".equalsIgnoreCase(node.path("type").asText())) return;

                        // done 事件发出时 fullAnswer / generatedTitle 已稳定，可安全快照
                        final String snapshotAnswer = fullAnswer.toString();
                        final String snapshotTitle = generatedTitle[0];
                        if (StrUtil.isBlank(question) || snapshotAnswer.isEmpty()) {
                            log.debug("跳过持久化: question 或 answer 为空, talkId={}", finalTalkId);
                            return;
                        }

                        // 快照本次请求携带的图片列表，随问题一起持久化
                        final List<String> snapshotImages = images;
                        Mono.fromRunnable(
                                () -> persistAndCleanCache(userId, finalTalkId, question, snapshotAnswer, snapshotTitle, snapshotImages))
                                .subscribeOn(Schedulers.boundedElastic())
                                .doOnError(e -> log.warn("异步持久化失败，进入重试队列: talkId={}", finalTalkId, e))
                                .onErrorResume(e -> {
                                    retryQueue.offer(new PersistenceTask(
                                            userId, finalTalkId, question, snapshotAnswer, snapshotTitle, snapshotImages, 0));
                                    return Mono.empty();
                                })
                                .subscribe();
                    } catch (Exception e) {
                        log.warn("doOnNext 解析事件失败, talkId={}, err={}", finalTalkId, e.getMessage());
                    }
                })

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

    /**
     * 解析 Python 模型层单行 SSE 事件 JSON，映射为 Java 侧标准事件字符串。
     *
     * <p>错误码约定（来自 Python error_codes.py）：
     * <ul>
     *   <li>E1001 — 模型推理超时，retryable=true</li>
     *   <li>E1002 — 模型拒绝回答（安全限制），retryable=false</li>
     *   <li>E1003 — 模型 OOM，retryable=true</li>
     *   <li>E1099 — 模型层未知错误，retryable=false</li>
     *   <li>E2xxx — Java 服务层错误（当前在 onErrorResume 中产生）</li>
     * </ul>
     * E1xxx 记录为 WARN（模型侧问题），E2xxx 记录为 ERROR（本层问题）。
     */
    private Flux<String> parseModelLine(String line,
                                        Long talkId,
                                        String[] generatedTitle,
                                        String[] updatedAllInfo,
                                        StringBuilder fullAnswer) {
        // ── 超长行保护：解析前先检查长度，防止 OOM ──────────────────────────────
        if (line.length() > MAX_LINE_LENGTH) {
            log.error("接收到超长 SSE 行，已截断拒绝解析: length={}, talkId={}, preview={}",
                    line.length(), talkId, line.substring(0, 200));
            try {
                Map<String, Object> warning = new HashMap<>();
                warning.put("type", "warning");
                warning.put("talkId", talkId.toString());
                warning.put("message", "单条消息超长已截断");
                return Flux.just(objectMapper.writeValueAsString(warning));
            } catch (Exception ex) {
                return Flux.empty();
            }
        }

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

            // error 事件：解析结构化错误码，分级日志，透传完整 error 对象
            if ("error".equalsIgnoreCase(type)) {
                JsonNode errorNode = json.path("error");
                // 提取结构化字段，若 error 对象缺失则降级到旧版 content 字段
                String errorCode = errorNode.path("code").asText("");
                boolean retryable = errorNode.path("retryable").asBoolean(false);
                String detail = errorNode.path("detail").asText("");
                // 优先取 error.message，降级到顶层 content（旧版 Python 兼容）
                String errorMessage = errorNode.isMissingNode()
                        ? json.path("content").asText("AI服务异常")
                        : errorNode.path("message").asText(
                                json.path("content").asText("AI服务异常"));

                // 按错误码前缀分级日志：E1xxx=模型层(WARN) / E2xxx=服务层(ERROR) / 其他(ERROR)
                if (errorCode.startsWith("E1")) {
                    log.warn("模型层错误事件: talkId={}, code={}, retryable={}, message={}, detail={}",
                            talkId, errorCode, retryable, errorMessage, detail);
                } else if (errorCode.startsWith("E2")) {
                    log.error("服务层错误事件: talkId={}, code={}, retryable={}, message={}, detail={}",
                            talkId, errorCode, retryable, errorMessage, detail);
                } else {
                    // 无结构化 code（旧版 Python 或未知来源）
                    log.error("错误事件（无结构化 code）: talkId={}, message={}", talkId, errorMessage);
                }

                // 构造 SSE error 输出：保留旧版 message 字段（前端向后兼容），附加完整 error 对象
                Map<String, Object> errorResp = new HashMap<>();
                errorResp.put("type", "error");
                errorResp.put("talkId", talkId.toString());
                errorResp.put("message", errorMessage);   // 旧前端读此字段
                if (!errorNode.isMissingNode()) {
                    // 透传完整结构化 error 对象，新前端/运维可直接读取 code/retryable
                    errorResp.put("error", objectMapper.convertValue(
                            errorNode, new TypeReference<Map<String, Object>>() {}));
                }
                return Flux.just(objectMapper.writeValueAsString(errorResp));
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

            // chunk 事件：流式报告片段（打字机效果），追加全文并直接转发前端
            if ("chunk".equalsIgnoreCase(type)) {
                String chunkContent = json.path("content").asText("");
                fullAnswer.append(chunkContent);
                Map<String, Object> chunkResp = baseResponse(talkId, generatedTitle[0], "chunk");
                chunkResp.put("content", chunkContent);
                return Flux.just(objectMapper.writeValueAsString(chunkResp));
            }

            // result 事件：非流式完整答案（irrelevant/knowledge 路径），追加全文并转发前端
            if ("result".equalsIgnoreCase(type)) {
                String chunk = json.path("content").asText("");
                fullAnswer.append(chunk);
                Map<String, Object> chunkResp = baseResponse(talkId, generatedTitle[0], "chunk");
                chunkResp.put("content", chunk);
                return Flux.just(objectMapper.writeValueAsString(chunkResp));
            }

            // heartbeat 事件：Python 端心跳保活，Java 侧静默丢弃，不透传前端
            if ("heartbeat".equalsIgnoreCase(type)) {
                return Flux.empty();
            }

            // 未知 type 兜底：包装为 meta 事件透传，不丢弃数据，log.info 方便未来扩展时发现
            log.info("收到未知 type 事件，透传为 meta: type={}, talkId={}", type, talkId);
            Map<String, Object> unknownResp = baseResponse(talkId, generatedTitle[0], "meta");
            unknownResp.put("originalType", type);
            unknownResp.put("content", objectMapper.convertValue(
                    json, new TypeReference<Map<String, Object>>() {}));
            return Flux.just(objectMapper.writeValueAsString(unknownResp));

        } catch (Exception e) {
            // JSON 解析失败或事件处理异常：warn 级别 + 截断原始行，跳过本条，不终止 Flux
            String preview = line.length() > 200 ? line.substring(0, 200) + "…" : line;
            log.warn("解析 SSE 行失败，已跳过: talkId={}, err={}, preview={}",
                    talkId, e.getMessage(), preview);
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

    /**
     * 执行持久化并清理 Redis 历史缓存。
     * 供 doOnNext 的异步 Mono 和 @Scheduled 重试任务共同调用。
     */
    private void persistAndCleanCache(Long userId, Long talkId,
                                      String question, String answer, String title, List<String> images) {
        log.info("异步持久化开始: talkId={}, answerLen={}", talkId, answer.length());
        conversationPersistenceService.persistConversation(
                userId, talkId, question, answer, "", title, images);
        // 持久化成功后清理历史缓存，保证下一轮对话能重新加载最新记录
        stringRedisTemplate.delete("chat:history:" + userId + ":" + talkId);
        log.info("异步持久化完成，已清理历史缓存: talkId={}", talkId);
    }

    /**
     * 定时重试失败的持久化任务，每 30 秒执行一次。
     * 超过 MAX_PERSIST_RETRIES 次的任务将被永久丢弃并记录 ERROR 日志（可对接告警）。
     */
    @Scheduled(fixedDelay = 30_000)
    public void retryFailedPersistence() {
        if (retryQueue.isEmpty()) return;

        // 快照当前队列大小，只重试本批次任务，避免无限循环处理新入队的任务
        int batchSize = retryQueue.size();
        log.info("持久化重试定时任务启动: 当前队列 {} 个任务", batchSize);

        for (int i = 0; i < batchSize; i++) {
            PersistenceTask task = retryQueue.poll();
            if (task == null) break;

            if (task.retryCount() >= MAX_PERSIST_RETRIES) {
                log.error("持久化重试已达上限 ({} 次)，永久丢弃: talkId={}", MAX_PERSIST_RETRIES, task.talkId());
                continue;
            }

            try {
                persistAndCleanCache(task.userId(), task.talkId(),
                        task.question(), task.answer(), task.title(), task.images());
                log.info("持久化重试成功: talkId={}, retryCount={}", task.talkId(), task.retryCount());
            } catch (Exception e) {
                int nextRetry = task.retryCount() + 1;
                log.warn("持久化重试失败 ({}/{}): talkId={}, err={}",
                        nextRetry, MAX_PERSIST_RETRIES, task.talkId(), e.getMessage(), e);
                // 重新入队，retryCount + 1
                retryQueue.offer(new PersistenceTask(
                        task.userId(), task.talkId(), task.question(),
                        task.answer(), task.title(), task.images(), nextRetry));
            }
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
            // 存入缓存前将 images 字段置空，避免 Base64 大字段撑爆 Redis
            // images 仅在前端请求历史记录时从数据库实时读取（getPreContent 走 DB 查询）
            List<Cont> cacheList = history.stream()
                    .map(c -> Cont.builder()
                            .id(c.getId())
                            .userId(c.getUserId())
                            .talkId(c.getTalkId())
                            .content(c.getContent())
                            .role(c.getRole())
                            .images(null)
                            .createTime(c.getCreateTime())
                            .build())
                    .collect(Collectors.toList());
            stringRedisTemplate.delete(key);
            stringRedisTemplate.opsForValue().set(key, objectMapper.writeValueAsString(cacheList), 1, TimeUnit.HOURS);
            log.debug("历史记录已写入缓存（images 已剔除）: key={}", key);
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
