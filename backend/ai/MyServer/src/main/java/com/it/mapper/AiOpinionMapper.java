package com.it.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.it.pojo.AiOpinion;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AiOpinionMapper extends BaseMapper<AiOpinion> {

    /** 查询指定病人最新一条 AI 分析记录 */
    @Select("SELECT * FROM ai_opinion WHERE patient_id = #{patientId} ORDER BY update_time DESC LIMIT 1")
    AiOpinion selectLatestByPatientId(Long patientId);
}
