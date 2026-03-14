package com.it.controller;

import com.it.po.uo.PatientParam;
import com.it.pojo.Result;
import com.it.service.IPatientService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

@RestController
@CrossOrigin("*")
@RequestMapping("/api/patients")
@Slf4j
@RequiredArgsConstructor
public class PatientController {

    private final IPatientService patientService;

    /** GET /api/patients?page=1&size=10&name=张三&diseases=糖尿病 */
    @GetMapping
    public Result getPatientPage(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) String name,
            @RequestParam(required = false) String diseases) {
        return patientService.getPatientPage(page, size, name, diseases);
    }

    /** POST /api/patients */
    @PostMapping
    public Result addPatient(@RequestBody PatientParam param) {
        return patientService.addPatient(param);
    }

    /** PUT /api/patients/{id} */
    @PutMapping("/{id}")
    public Result updatePatient(@PathVariable Long id, @RequestBody PatientParam param) {
        return patientService.updatePatient(id, param);
    }

    /** DELETE /api/patients/{id} */
    @DeleteMapping("/{id}")
    public Result deletePatient(@PathVariable Long id) {
        return patientService.deletePatient(id);
    }

    /** GET /api/patients/{id} */
    @GetMapping("/{id}")
    public Result getPatientDetail(@PathVariable Long id) {
        return patientService.getPatientDetail(id);
    }
}
