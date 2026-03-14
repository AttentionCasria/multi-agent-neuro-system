package com.it.po.vo;

import lombok.Data;

@Data
public class AiSyncTalkVO {
    private Long        patientId;
    private boolean     updated;
    private AiOpinionVO aiOpinion;
    private Long        talkId;
}
