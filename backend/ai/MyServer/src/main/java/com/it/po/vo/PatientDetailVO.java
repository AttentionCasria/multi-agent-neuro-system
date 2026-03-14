package com.it.po.vo;

import lombok.Data;

/** 病人详情（aiOpinion 为完整对象） */
@Data
public class PatientDetailVO {

    private Long id;

    private String name;

    private String history;

    private String notes;

    private AiOpinionVO aiOpinion;
}
