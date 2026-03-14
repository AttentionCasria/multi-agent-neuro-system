package com.it.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.it.mapper.LearningMaterialMapper;
import com.it.po.vo.LearningMaterialDetailVO;
import com.it.po.vo.LearningMaterialPageVO;
import com.it.po.vo.LearningMaterialVO;
import com.it.pojo.LearningMaterial;
import com.it.pojo.Result;
import com.it.service.ILearningMaterialService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

@Service
@RequiredArgsConstructor
public class LearningMaterialServiceImpl
        extends ServiceImpl<LearningMaterialMapper, LearningMaterial>
        implements ILearningMaterialService {

    @Override
    public Result getPage(String category, int page, int size) {
        LambdaQueryWrapper<LearningMaterial> wrapper = new LambdaQueryWrapper<>();
        if (StringUtils.hasText(category)) {
            wrapper.eq(LearningMaterial::getCategory, category);
        }
        wrapper.orderByDesc(LearningMaterial::getCreateTime);

        Page<LearningMaterial> pageResult = this.page(new Page<>(page, size), wrapper);

        List<LearningMaterialVO> vos = pageResult.getRecords().stream().map(m -> {
            LearningMaterialVO vo = new LearningMaterialVO();
            vo.setId(m.getId());
            vo.setTitle(m.getTitle());
            vo.setType(m.getType());
            vo.setUrl(m.getUrl());
            return vo;
        }).toList();

        LearningMaterialPageVO pageVO = new LearningMaterialPageVO();
        pageVO.setTotal(pageResult.getTotal());
        pageVO.setMaterials(vos);

        return Result.success(pageVO);
    }

    @Override
    public Result getDetail(Long id) {
        LearningMaterial m = this.getById(id);
        if (m == null) {
            return Result.error("资料不存在");
        }
        LearningMaterialDetailVO vo = new LearningMaterialDetailVO();
        vo.setId(m.getId());
        vo.setTitle(m.getTitle());
        vo.setContent(m.getContent());
        return Result.success(vo);
    }
}
