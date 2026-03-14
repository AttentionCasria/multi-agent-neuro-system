package com.it.controller;

import com.it.pojo.Result;
import com.it.service.ILearningMaterialService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

@RestController
@CrossOrigin("*")
@RequestMapping("/api/learning-materials")
@Slf4j
@RequiredArgsConstructor
public class LearningMaterialController {

    private final ILearningMaterialService learningMaterialService;

    /** GET /api/learning-materials?category=心血管疾病&page=1&size=10 */
    @GetMapping
    public Result getPage(
            @RequestParam(required = false) String category,
            @RequestParam(defaultValue = "1")  int page,
            @RequestParam(defaultValue = "10") int size) {
        return learningMaterialService.getPage(category, page, size);
    }

    /** GET /api/learning-materials/{id} */
    @GetMapping("/{id}")
    public Result getDetail(@PathVariable Long id) {
        return learningMaterialService.getDetail(id);
    }
}
