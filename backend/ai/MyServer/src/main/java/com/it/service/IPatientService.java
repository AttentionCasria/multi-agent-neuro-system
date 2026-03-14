package com.it.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.it.po.uo.PatientParam;
import com.it.pojo.Patient;
import com.it.pojo.Result;

public interface IPatientService extends IService<Patient> {

    Result getPatientPage(int page, int size, String name, String diseases);

    Result addPatient(PatientParam param);

    Result updatePatient(Long id, PatientParam param);

    Result deletePatient(Long id);

    Result getPatientDetail(Long id);
}
