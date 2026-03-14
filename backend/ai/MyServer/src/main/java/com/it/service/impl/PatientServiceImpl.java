package com.it.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.it.mapper.AiOpinionMapper;
import com.it.mapper.PatientMapper;
import com.it.po.uo.PatientParam;
import com.it.po.vo.AiOpinionVO;
import com.it.po.vo.PatientDetailVO;
import com.it.po.vo.PatientPageVO;
import com.it.po.vo.PatientVO;
import com.it.pojo.AiOpinion;
import com.it.pojo.Patient;
import com.it.pojo.Result;
import com.it.service.IPatientService;
import com.it.utils.ThreadLocalUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Service
@Transactional
@RequiredArgsConstructor
public class PatientServiceImpl extends ServiceImpl<PatientMapper, Patient> implements IPatientService {

    private final AiOpinionMapper aiOpinionMapper;

    /** 从 ThreadLocal 获取当前登录医生 ID */
    private Long currentDoctorId() {
        return ThreadLocalUtil.getCurrentUser().getId();
    }

    @Override
    public Result getPatientPage(int page, int size, String name, String diseases) {
        Long doctorId = currentDoctorId();

        LambdaQueryWrapper<Patient> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Patient::getDoctorId, doctorId);
        if (StringUtils.hasText(name)) {
            wrapper.like(Patient::getName, name);
        }
        if (StringUtils.hasText(diseases)) {
            wrapper.like(Patient::getHistory, diseases);
        }
        wrapper.orderByDesc(Patient::getUpdateTime);

        Page<Patient> pageResult = this.page(new Page<>(page, size), wrapper);
        List<Patient> records = pageResult.getRecords();

        List<PatientVO> patientVOs = new ArrayList<>(records.size());
        for (Patient patient : records) {
            PatientVO vo = new PatientVO();
            vo.setId(patient.getId());
            vo.setName(patient.getName());
            vo.setHistory(patient.getHistory());
            vo.setNotes(patient.getNotes());

            AiOpinion opinion = aiOpinionMapper.selectLatestByPatientId(patient.getId());
            if (opinion != null) {
                StringBuilder sb = new StringBuilder();
                if (StringUtils.hasText(opinion.getSuggestions())) {
                    sb.append(opinion.getSuggestions());
                }
                if (StringUtils.hasText(opinion.getRiskLevel())) {
                    if (sb.length() > 0) sb.append("，");
                    sb.append("风险等级：").append(opinion.getRiskLevel());
                }
                if (sb.length() > 0) {
                    vo.setAiOpinion(sb.toString());
                }
            }
            patientVOs.add(vo);
        }

        PatientPageVO pageVO = new PatientPageVO();
        pageVO.setTotal(pageResult.getTotal());
        pageVO.setPatients(patientVOs);

        return Result.success(pageVO);
    }

    @Override
    public Result addPatient(PatientParam param) {
        Long doctorId = currentDoctorId();

        Patient patient = new Patient();
        patient.setName(param.getName());
        patient.setHistory(param.getHistory());
        patient.setNotes(param.getNotes());
        patient.setDoctorId(doctorId);
        this.save(patient);

        return Result.success(Map.of("id", patient.getId()));
    }

    @Override
    public Result updatePatient(Long id, PatientParam param) {
        Long doctorId = currentDoctorId();
        Patient patient = this.getById(id);
        if (patient == null || !doctorId.equals(patient.getDoctorId())) {
            return Result.error("病人不存在或无权限");
        }

        patient.setName(param.getName());
        patient.setHistory(param.getHistory());
        patient.setNotes(param.getNotes());
        this.updateById(patient);

        return Result.success();
    }

    @Override
    public Result deletePatient(Long id) {
        Long doctorId = currentDoctorId();
        Patient patient = this.getById(id);
        if (patient == null || !doctorId.equals(patient.getDoctorId())) {
            return Result.error("病人不存在或无权限");
        }

        // 先删关联的 AI 分析记录，避免外键约束报错
        LambdaQueryWrapper<AiOpinion> opWrapper = new LambdaQueryWrapper<>();
        opWrapper.eq(AiOpinion::getPatientId, id);
        aiOpinionMapper.delete(opWrapper);

        this.removeById(id);
        return Result.success();
    }

    @Override
    public Result getPatientDetail(Long id) {
        Long doctorId = currentDoctorId();
        Patient patient = this.getById(id);
        if (patient == null || !doctorId.equals(patient.getDoctorId())) {
            return Result.error("病人不存在或无权限");
        }

        PatientDetailVO vo = new PatientDetailVO();
        vo.setId(patient.getId());
        vo.setName(patient.getName());
        vo.setHistory(patient.getHistory());
        vo.setNotes(patient.getNotes());

        AiOpinion opinion = aiOpinionMapper.selectLatestByPatientId(id);
        if (opinion != null) {
            AiOpinionVO opVO = new AiOpinionVO();
            opVO.setRiskLevel(opinion.getRiskLevel());
            opVO.setSuggestion(opinion.getSuggestions());
            opVO.setAnalysisDetails(opinion.getAnalysisDetails());
            opVO.setLastUpdatedAt(opinion.getUpdateTime());
            vo.setAiOpinion(opVO);
        }

        return Result.success(vo);
    }
}
