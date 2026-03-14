package com.it.po.vo;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class AiOpinionVO {

    private String riskLevel;

    private String suggestion;

    private String analysisDetails;

    private LocalDateTime lastUpdatedAt;
}
