a# 想法



1.历史病历与个人画像系统
电子健康档案(EHR)集成:建立个人健康数据库，整合历史检查报告、用药记录和诊断结果，形成完整的个人健康画像，AI自动提取关键异常指标并生成“结果概览+可能诊断+需补充检查"提示，推送定制化健康建议和预防措施，实现"预防一诊疗一康复一健康管理"的全链条服务。
健康趋势分析:基于历史数据，系统可生成健康趋势图表，帮助用户直观了解自身健康变化。

2.社区与知识教育功能
医患互动社区:创建患者交流平台，用户可分享治疗经验、提问健康问题，由专业医生定期解答。
健康知识库:整合权威医学知识，提供疾病预防、健康生活方式等内容。




知识教育等辅助功能，历史病历



AI分析可以就以前的病史分析诊断，更重要的是要对现在的检查报告进行ai诊断，我觉得ai这一块应该把检查检验报告也纳入ai，同时ai诊断分析后可以再做一个就医指南模块





# 健康管理系统接口文档

1. **统一响应格式**：

   ```json
   {
     "code": 1,
     "msg": "success",
     "data": "内容（没有内容就是null）"
   }
   ```

2. **认证要求**：

   - 所有接口请求需携带 `Authorization` 头部：`<JWT token>`

3. **错误码定义**：

   | 错误码 | 说明           |
   | ------ | -------------- |
   | 400    | 参数错误       |
   | 401    | 未授权         |
   | 404    | 资源不存在     |
   | 500    | 服务器内部错误 |

4. **测试地址**：

   - 后端：`http://localhost:8080`
   - AI模型：`http://localhost:8000`

5. 所有接口均以 `/api` 为前缀，例如 `/patients` 实际请求路径为 `/api/patients`。



------

## 一、病人管理页面接口 ⏳ （前后端工作）待实现

**功能描述**：医生对病人信息的管理，包括查看、新增、修改、删除病人信息，以及查看AI对病人的分析意见。

### 1. 获取病人列表（分页）

- **接口地址**：`GET /patients`
- **请求参数**：

```json
{
  "page": 1,
  "size": 10,
  "filter": {
    "name": "张三",
    "diseases": "糖尿病"
  }
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "total": 100,
    "patients": [
      {
        "id": 1,
        "name": "张三",
        "history": "糖尿病，高血压",
        "notes": "避免高糖饮食，定期检查血糖",
        "aiOpinion": "建议增加运动监测，风险等级：中"
      }
    ]
  }
}
```

### 2. 新增病人

- **接口地址**：`POST /patients`
- **请求参数**：

```json
{
  "name": "李四",
  "history": "心脏病，过敏史",
  "notes": "每日服药，避免剧烈运动"
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "id": 2
  }
}
```

### 3. 修改病人信息

- **接口地址**：`PUT /patients/{id}`
- **请求参数**：

```json
{
  "name": "李四（更新）",
  "history": "心脏病，过敏史",
  "notes": "新增备注：注意睡眠质量"
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": null
}
```

### 4. 删除病人

- **接口地址**：`DELETE /patients/{id}`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": null
}
```

### 5. 获取单个病人详情（含AI分析）

- **接口地址**：`GET /patients/{id}`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "id": 1,
    "name": "张三",
    "history": "糖尿病，高血压",
    "notes": "避免高糖饮食，定期检查血糖",
    "aiOpinion": {
      "riskLevel": "高",
      "suggestion": "调整用药方案",
      "analysisDetails": "血压超标，结合病史糖尿病，存在心血管并发症风险",
      "lastUpdatedAt": "2026-03-11T20:05:00"
    }
  }
}
```

**权限要求**：需要医生登录后携带JWT token访问。

------

## 二、医生学习页面接口 ⏳ （前后端工作）待实现

**功能描述**：提供学习资料查询功能。

### 1. 获取学习资料列表

- **接口地址**：`GET /learning-materials`
- **请求参数**：

```json
{
  "category": "心血管疾病",
  "page": 1,
  "size": 10
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "total": 50,
    "materials": [
      {
        "id": 1,
        "title": "高血压防治指南",
        "type": "文档",
        "url": "xxx.pdf"
      }
    ]
  }
}
```

### 2. 获取学习资料详情

- **接口地址**：`GET /learning-materials/{id}`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "id": 1,
    "title": "高血压防治指南",
    "content": "详细内容或文件链接"
  }
}
```

**权限要求**：需医生登录后访问。

------

## 三、AI端接口 ⏳ （前、后、模型端工作）待实现

**功能描述**：提供AI分析病人的健康数据并生成建议，支持同步用户对话记录进行综合分析。

### 1. AI分析病人健康风险（后端请求模型端）

- **接口地址**：`POST /ai/analyze`
- **请求参数**：

```json
{
  "patientId": 1,
  "data": "ggjhfgjjhgg"
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "riskLevel": "高风险",
    "suggestion": "控制饮食，减少盐分摄入",
    "analysisDetails": "血压超标，结合病史糖尿病，存在心血管并发症风险"
  }
}
```

### 2. 同步用户对话到AI分析（前后端工作）（新增）

**功能描述**：将用户与AI模型的对话记录同步到健康管理系统，AI会分析对话内容并与病人已有的健康建议综合，更新病人的aiOpinion。

- **接口地址**：`POST /ai/sync-talk`
- **请求参数**：

```json
{
  "patientId": 1,
  "talkId": 5,
  "conversation": [
    {
      "role": "user",
      "content": "我四肢抽搐，是什么病？"
    },
    {
      "role": "assistant",
      "content": "这是综合诊疗结果：基于您提供的病史信息..."
    },
    {
      "role": "user",
      "content": "我还头痛欲裂，口吐白沫，这是什么病？"
    },
    {
      "role": "assistant",
      "content": "这是综合诊疗结果：基于您提供的医疗历史信息..."
    }
  ],
  "mergeWithHistory": true
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "patientId": 1,
    "updated": true,
    "aiOpinion": {
      "riskLevel": "高风险",
      "suggestion": "立即就医，进行脑电图和MRI检查",
      "analysisDetails": "结合对话症状（四肢抽搐、口吐白沫、剧烈头痛）与病史（糖尿病、高血压），存在癫痫发作及心血管并发症风险，建议尽快神经科就诊",
      "lastUpdatedAt": "2026-03-11T20:05:00"
    },
    "talkId": 5
  }
}
```

**权限要求**：需医生登录后携带JWT token访问。

**错误码**：

- 400：参数错误（如patientId或talkId不存在）
- 401：未授权
- 404：病人或对话记录不存在
- 500：AI分析服务异常

**备注**：

1. 该接口调用成功后，病人管理模块的 `GET /patients/{id}` 接口返回的 `aiOpinion` 将自动更新。
2. 对话内容会经过脱敏处理后发送给AI端进行分析。
3. 建议在前端用户确认后再调用此接口，避免频繁同步。

------

## 四、用户认证接口 ✅ 已实现

**功能描述**：提供用户注册、登录、退出、信息管理等功能。

### 1. 注册

- **接口地址**：`POST /user/register`
- **请求参数**：

```json
{
  "name": "Casria",
  "password": "123456",
  "image": ""
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "name": "Casria007",
    "token": "eyJhbGciOiJIUzI1NiJ9..."
  }
}
```

### 2. 登录

- **接口地址**：`POST /user/login`
- **请求参数**：

```json
{
  "name": "darkside",
  "password": "Gong"
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "name": "darkside",
    "image": "",
    "token": "eyJhbGciOiJIUzI1NiJ9..."
  }
}
```

### 3. 退出登录

- **接口地址**：`POST /user/logOut`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": "退出成功"
}
```

**后端操作**：销毁token

### 4. 上传文件

- **接口地址**：`POST /user/upload`
- **请求参数**：

```json
{
  "file": ""
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": "网址"
}
```

### 5. 展示本人信息

- **接口地址**：`GET /user/showInfo`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": "darkside"
}
```

### 6. 修改信息

- **接口地址**：`PUT /user/showInfo/changeKey`
- **请求参数**：

```json
{
  "prePassword": "Gong",
  "newPassword": "123456",
  "image": ""
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": null
}
```

------

## 五、用户对话接口 ✅ 已实现

**功能描述**：提供用户与AI模型的对话管理功能。

### 1. 获取对话列表（初始页面）

- **接口地址**：`GET /user/title`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": [
    {
      "talkId": 5,
      "title": "四肢抽搐病因分析"
    },
    {
      "talkId": 4,
      "title": "口吐白沫病因分析"
    }
  ]
}
```

### 2. 获取对话记录

- **接口地址**：`GET /user/ques/getQues/{talk_id}`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": [
    "我四肢抽搐，是什么病？",
    "这是综合诊疗结果：...",
    "我还头痛欲裂，口吐白沫，这是什么病？",
    "这是综合诊疗结果：..."
  ]
}
```

### 3. 发送问题

- **接口地址**：`POST /user/ques/getQues`
- **请求参数**：

```json
{
  "talkId": 5,
  "question": "我还头痛欲裂，口吐白沫，这是什么病？"
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "talkId": null,
    "title": null,
    "content": "这是综合诊疗结果：..."
  }
}
```

### 4. 新建对话

- **接口地址**：`POST /user/ques/newGetQues`
- **请求参数**：

```json
{
  "question": "我四肢抽搐，是什么病？"
}
```

- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "talkId": 5,
    "title": "四肢抽搐病因分析",
    "content": "这是综合诊疗结果：..."
  }
}
```

### 5. 删除对话信息

- **接口地址**：`DELETE /user/deleteTalk/{talk_id}`
- **响应数据**：

```json
{
  "code": 1,
  "msg": "success",
  "data": null
}
```

------

## 六、AI模型接口（后端与模型端）⏳ 待实现

**功能描述**：后端与AI模型端的通信接口。

### 1. 获取AI分析结果

- **接口地址**：`POST /model/get_result`
- **请求参数**：

```json
{
  "question": "",
  "round": 2,
  "all_info": ""
}
```

- **响应数据**：

```json
{
  "result": "这是综合诊疗结果：...",
  "summary": "总结对后续医疗诊断有用的内容...",
  "name": "口吐白沫病因分析"
}
```





# 数据库表

```sql
DROP TABLE IF EXISTS patient;
CREATE TABLE patient (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '病人ID',
    name VARCHAR(64) NOT NULL COMMENT '病人姓名',
    history TEXT COMMENT '既往病史',
    notes TEXT COMMENT '注意事项/医嘱',
    doctor_id BIGINT UNSIGNED NOT NULL COMMENT '负责医生ID(关联med_user)',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_doctor_id(doctor_id),
    CONSTRAINT fk_patient_doctor FOREIGN KEY (doctor_id) REFERENCES med_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;




DROP TABLE IF EXISTS ai_opinion;
CREATE TABLE ai_opinion (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    patient_id BIGINT UNSIGNED NOT NULL COMMENT '病人ID',
    risk_level VARCHAR(16) COMMENT '风险等级(低/中/高)',
    suggestions TEXT COMMENT 'AI建议(JSON数组)',
    analysis_details TEXT COMMENT '分析详情',
    source_type VARCHAR(16) DEFAULT 'health_data' COMMENT '来源类型(health_data/sync_talk)',
    source_id BIGINT UNSIGNED COMMENT '来源ID(健康数据ID或talk_id)',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_patient_id(patient_id),
    CONSTRAINT fk_ai_opinion_patient FOREIGN KEY (patient_id) REFERENCES patient(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;




DROP TABLE IF EXISTS health_data;
CREATE TABLE health_data (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    patient_id BIGINT UNSIGNED NOT NULL COMMENT '病人ID',
    data_content TEXT NOT NULL COMMENT '健康数据(JSON格式，如血压、血糖等)',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_patient_id(patient_id),
    CONSTRAINT fk_health_data_patient FOREIGN KEY (patient_id) REFERENCES patient(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


DROP TABLE IF EXISTS learning_material;
CREATE TABLE learning_material (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '资料ID',
    title VARCHAR(128) NOT NULL COMMENT '资料标题',
    category VARCHAR(64) COMMENT '分类(如心血管疾病)',
    type VARCHAR(32) COMMENT '类型(文档/视频/链接)',
    url VARCHAR(512) COMMENT '文件链接',
    content TEXT COMMENT '详细内容',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

```

