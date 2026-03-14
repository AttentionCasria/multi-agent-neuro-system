package com.it.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.it.pojo.LearningMaterial;
import com.it.pojo.Result;

public interface ILearningMaterialService extends IService<LearningMaterial> {

    Result getPage(String category, int page, int size);

    Result getDetail(Long id);
}
