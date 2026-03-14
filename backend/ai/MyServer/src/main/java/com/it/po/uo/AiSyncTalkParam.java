package com.it.po.uo;

import lombok.Data;

import java.util.List;

@Data
public class AiSyncTalkParam {
    private Long                    patientId;
    private Long                    talkId;
    private List<ConversationMessage> conversation;
    /** 是否与病人既往病史合并分析 */
    private boolean                 mergeWithHistory;
}
