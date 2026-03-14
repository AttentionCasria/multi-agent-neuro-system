package com.it.pojo;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("patient")
public class Patient {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    private String history;

    private String notes;

    /** 负责医生ID，关联 med_user.id */
    private Long doctorId;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
