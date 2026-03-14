package com.it.po.vo;

import lombok.Data;

/** 病人列表条目（aiOpinion 为摘要字符串） */
@Data
public class PatientVO {

    private Long id;

    private String name;

    private String history;

    private String notes;

    private String aiOpinion;
}
