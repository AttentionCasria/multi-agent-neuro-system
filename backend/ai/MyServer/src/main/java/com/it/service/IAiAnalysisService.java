package com.it.service;

import com.it.po.uo.AiAnalyzeParam;
import com.it.po.uo.AiSyncTalkParam;
import com.it.pojo.Result;

public interface IAiAnalysisService {

    Result analyze(AiAnalyzeParam param, String token);

    Result syncTalk(AiSyncTalkParam param, String token);
}
