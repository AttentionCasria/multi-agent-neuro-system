package com.it.po.uo;

import lombok.Data;

/** 新增 / 修改病人的请求体 */
@Data
public class PatientParam {

    private String name;

    private String history;

    private String notes;
}
