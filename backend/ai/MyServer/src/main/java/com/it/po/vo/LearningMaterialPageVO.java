package com.it.po.vo;

import lombok.Data;

import java.util.List;

@Data
public class LearningMaterialPageVO {
    private long                    total;
    private List<LearningMaterialVO> materials;
}
