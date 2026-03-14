package com.it.po.uo;

import lombok.Data;

@Data
public class AiAnalyzeParam {
    /** 病人ID */
    private Long   patientId;
    /** 本次健康数据（如血压、血糖等描述文本或JSON字符串） */
    private String data;
}
