package com.it.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.it.mapper.AiOpinionMapper;
import com.it.mapper.HealthDataMapper;
import com.it.mapper.PatientMapper;
import com.it.po.uo.AiAnalyzeParam;
import com.it.po.uo.AiSyncTalkParam;
import com.it.po.uo.ConversationMessage;
import com.it.po.vo.AiAnalyzeVO;
import com.it.po.vo.AiOpinionVO;
import com.it.po.vo.AiSyncTalkVO;
import com.it.pojo.AiOpinion;
import com.it.pojo.HealthData;
import com.it.pojo.Patient;
import com.it.pojo.Result;
import com.it.service.IAiAnalysisService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
@Slf4j
public class AiAnalysisServiceImpl implements IAiAnalysisService {

    private final WebClient        webClient;
    private final PatientMapper    patientMapper;
    private final HealthDataMapper healthDataMapper;
    private final AiOpinionMapper  aiOpinionMapper;
    private final ObjectMapper     objectMapper;

    // ─────────────────────────────────────────────────────────────────────────
    // POST /api/ai/analyze
    // ─────────────────────────────────────────────────────────────────────────
    @Transactional
    @Override
    public Result analyze(AiAnalyzeParam param, String token) {
        if (param.getPatientId() == null || !StringUtils.hasText(param.getData())) {
            return Result.error("patientId 和 data 不能为空");
        }

        Patient patient = patientMapper.selectById(param.getPatientId());
        if (patient == null) {
            return Result.error("病人不存在");
        }

        // 持久化本次健康数据
        HealthData hd = new HealthData();
        hd.setPatientId(param.getPatientId());
        hd.setDataContent(param.getData());
        healthDataMapper.insert(hd);

        // 构建发给 AI 的问题
        String question = buildAnalyzeQuestion(patient, param.getData());

        // 调用 AI 模型（同步收集完整答案）
        String answer = callModel(question, "", token);
        if (answer == null) {
            return Result.error("AI 分析服务异常");
        }

        // 解析 AI 答案
        String riskLevel       = extractRiskLevel(answer);
        String suggestion      = extractSection(answer, "建议");
        String analysisDetails = extractSection(answer, "分析");

        // 写入 ai_opinion
        AiOpinion opinion = new AiOpinion();
        opinion.setPatientId(param.getPatientId());
        opinion.setRiskLevel(riskLevel);
        opinion.setSuggestions(StringUtils.hasText(suggestion) ? suggestion : answer);
        opinion.setAnalysisDetails(StringUtils.hasText(analysisDetails) ? analysisDetails : answer);
        opinion.setSourceType("health_data");
        opinion.setSourceId(hd.getId());
        aiOpinionMapper.insert(opinion);

        AiAnalyzeVO vo = new AiAnalyzeVO();
        vo.setRiskLevel(riskLevel);
        vo.setSuggestion(opinion.getSuggestions());
        vo.setAnalysisDetails(opinion.getAnalysisDetails());
        return Result.success(vo);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // POST /api/ai/sync-talk
    // ─────────────────────────────────────────────────────────────────────────
    @Transactional
    @Override
    public Result syncTalk(AiSyncTalkParam param, String token) {
        if (param.getPatientId() == null || param.getConversation() == null || param.getConversation().isEmpty()) {
            return Result.error("patientId 和 conversation 不能为空");
        }

        Patient patient = patientMapper.selectById(param.getPatientId());
        if (patient == null) {
            return Result.error("病人不存在");
        }

        String conversationText = buildConversationText(param.getConversation());

        // 如果需要合并病史，把病史拼进 all_info
        String allInfo = "";
        if (param.isMergeWithHistory() && StringUtils.hasText(patient.getHistory())) {
            allInfo = "病人既往病史：" + patient.getHistory() + "\n";
        }

        String question = "请根据以下医患对话内容" +
                (param.isMergeWithHistory() ? "并结合病人既往病史" : "") +
                "，对病人进行综合健康风险评估，给出风险等级（低/中/高）、改善建议和详细分析。\n\n" +
                "【对话内容】\n" + conversationText;

        String answer = callModel(question, allInfo, token);
        if (answer == null) {
            return Result.error("AI 分析服务异常");
        }

        String riskLevel       = extractRiskLevel(answer);
        String suggestion      = extractSection(answer, "建议");
        String analysisDetails = extractSection(answer, "分析");

        AiOpinion opinion = new AiOpinion();
        opinion.setPatientId(param.getPatientId());
        opinion.setRiskLevel(riskLevel);
        opinion.setSuggestions(StringUtils.hasText(suggestion) ? suggestion : answer);
        opinion.setAnalysisDetails(StringUtils.hasText(analysisDetails) ? analysisDetails : answer);
        opinion.setSourceType("sync_talk");
        opinion.setSourceId(param.getTalkId());
        aiOpinionMapper.insert(opinion);

        AiOpinionVO opinionVO = new AiOpinionVO();
        opinionVO.setRiskLevel(riskLevel);
        opinionVO.setSuggestion(opinion.getSuggestions());
        opinionVO.setAnalysisDetails(opinion.getAnalysisDetails());
        opinionVO.setLastUpdatedAt(LocalDateTime.now());

        AiSyncTalkVO vo = new AiSyncTalkVO();
        vo.setPatientId(param.getPatientId());
        vo.setUpdated(true);
        vo.setAiOpinion(opinionVO);
        vo.setTalkId(param.getTalkId());
        return Result.success(vo);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 私有辅助方法
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * 调用 AI 模型（阻塞式，收集流式响应中所有 result 片段拼成完整答案）。
     * 若模型不可用返回 null。
     */
    private String callModel(String question, String allInfo, String token) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("question", question);
            body.put("round", 1);
            body.put("all_info", allInfo == null ? "" : allInfo);
            body.put("token", token == null ? "" : token);
            body.put("report_mode", "analysis");
            body.put("show_thinking", false);

            // 收集完整的流式响应
            List<String> lines = webClient.post()
                    .uri("/model/get_result")
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.TEXT_PLAIN)
                    .bodyValue(body)
                    .retrieve()
                    .bodyToFlux(String.class)
                    .collectList()
                    .block();

            if (lines == null || lines.isEmpty()) return null;

            StringBuilder sb = new StringBuilder();
            for (String line : lines) {
                String trimmed = line.trim();
                if (trimmed.startsWith("data:")) trimmed = trimmed.substring(5).trim();
                if (trimmed.isEmpty() || "[DONE]".equalsIgnoreCase(trimmed)) continue;
                try {
                    JsonNode node = objectMapper.readTree(trimmed);
                    if (node.has("result")) {
                        sb.append(node.get("result").asText());
                    }
                } catch (Exception ignored) {
                    // 非 JSON 行，跳过
                }
            }
            return sb.length() > 0 ? sb.toString() : null;
        } catch (Exception e) {
            log.error("调用 AI 模型失败: {}", e.getMessage(), e);
            return null;
        }
    }

    private String buildAnalyzeQuestion(Patient patient, String data) {
        StringBuilder sb = new StringBuilder();
        sb.append("请对以下病人的健康数据进行专业医疗分析，给出风险等级（低/中/高）、改善建议和详细分析。\n\n");
        sb.append("【病人信息】\n姓名：").append(patient.getName()).append("\n");
        if (StringUtils.hasText(patient.getHistory())) {
            sb.append("既往病史：").append(patient.getHistory()).append("\n");
        }
        if (StringUtils.hasText(patient.getNotes())) {
            sb.append("医嘱：").append(patient.getNotes()).append("\n");
        }
        sb.append("\n【本次健康数据】\n").append(data);
        return sb.toString();
    }

    private String buildConversationText(List<ConversationMessage> messages) {
        StringBuilder sb = new StringBuilder();
        for (ConversationMessage msg : messages) {
            sb.append(msg.getRole()).append(": ").append(msg.getContent()).append("\n");
        }
        return sb.toString();
    }

    /** 从 AI 返回文本中提取风险等级关键词 */
    private String extractRiskLevel(String text) {
        if (text == null) return "未知";
        if (text.contains("高风险") || text.contains("高危") ||
                (text.contains("高") && text.contains("风险"))) return "高";
        if (text.contains("中风险") || text.contains("中度") ||
                (text.contains("中") && text.contains("风险"))) return "中";
        if (text.contains("低风险") || text.contains("低危") ||
                (text.contains("低") && text.contains("风险"))) return "低";
        return "中";
    }

    /**
     * 从 AI 文本中提取特定小节内容（如"建议：XXX"段落）。
     * 找不到时返回 null，由调用方降级处理。
     */
    private String extractSection(String text, String sectionName) {
        if (text == null) return null;
        int idx = text.indexOf(sectionName + "：");
        if (idx < 0) idx = text.indexOf(sectionName + ":");
        if (idx < 0) return null;
        int start = idx + sectionName.length() + 1;
        // 截取到下一个"段落标题"或文本末尾
        int end = text.length();
        for (String marker : new String[]{"风险等级", "建议", "分析", "总结"}) {
            if (marker.equals(sectionName)) continue;
            int next = text.indexOf(marker, start);
            if (next > start && next < end) end = next;
        }
        return text.substring(start, end).trim();
    }
}
