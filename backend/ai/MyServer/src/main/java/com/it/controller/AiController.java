package com.it.controller;

import com.it.po.uo.AiAnalyzeParam;
import com.it.po.uo.AiSyncTalkParam;
import com.it.pojo.Result;
import com.it.service.IAiAnalysisService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

@RestController
@CrossOrigin("*")
@RequestMapping("/api/ai")
@Slf4j
@RequiredArgsConstructor
public class AiController {

    private final IAiAnalysisService aiAnalysisService;

    /**
     * POST /api/ai/analyze
     * 对病人健康数据进行 AI 风险分析
     */
    @PostMapping("/analyze")
    public Result analyze(
            @RequestBody AiAnalyzeParam param,
            @RequestHeader(value = "token", required = false) String token,
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        String resolvedToken = resolveToken(token, authorization);
        return aiAnalysisService.analyze(param, resolvedToken);
    }

    /**
     * POST /api/ai/sync-talk
     * 将医患对话同步给 AI 进行综合分析，更新 aiOpinion
     */
    @PostMapping("/sync-talk")
    public Result syncTalk(
            @RequestBody AiSyncTalkParam param,
            @RequestHeader(value = "token", required = false) String token,
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        String resolvedToken = resolveToken(token, authorization);
        return aiAnalysisService.syncTalk(param, resolvedToken);
    }

    private String resolveToken(String token, String authorization) {
        if (token != null && !token.isBlank()) return token.trim();
        if (authorization != null && !authorization.isBlank()) {
            String v = authorization.trim();
            return v.startsWith("Bearer ") ? v.substring(7).trim() : v;
        }
        return null;
    }
}
