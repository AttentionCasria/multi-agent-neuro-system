package com.it.service;

import com.aliyun.oss.HttpMethod;
import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import com.aliyun.oss.model.GeneratePresignedUrlRequest;
import com.aliyun.oss.model.ListObjectsV2Request;
import com.aliyun.oss.model.ListObjectsV2Result;
import com.aliyun.oss.model.OSSObjectSummary;
import com.aliyun.oss.model.ResponseHeaderOverrides;
import com.it.pojo.AliOssProperties;
import com.it.pojo.DocumentUrlVO;
import com.it.pojo.DocumentVO;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * OSS 文档访问服务
 * 负责列出 documents/ 下的 PDF、生成签名 URL、按文献名模糊匹配
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OssDocumentService {

    private final AliOssProperties ossProperties;

    /** 长连接 OSS 客户端，在 Bean 生命周期内复用 */
    private OSS ossClient;

    @PostConstruct
    public void init() {
        ossClient = new OSSClientBuilder().build(
                ossProperties.getEndpoint(),
                ossProperties.getAccessKeyId(),
                ossProperties.getAccessKeySecret()
        );
        log.info("[OSS] 文档服务初始化完成，bucket={}, prefix={}",
                ossProperties.getBucketName(), ossProperties.getDocumentPrefix());
    }

    @PreDestroy
    public void destroy() {
        if (ossClient != null) {
            ossClient.shutdown();
        }
    }

    /**
     * 列出 documents/ 下所有 PDF，按第一级子目录（分类）分组返回
     * 返回结构：{ "指南": [{id, name, category, size}, ...], "教材": [...] }
     */
    public Map<String, List<DocumentVO>> listDocuments() {
        String prefix = ossProperties.getDocumentPrefix();
        ListObjectsV2Request req = new ListObjectsV2Request(ossProperties.getBucketName());
        req.setPrefix(prefix);
        req.setMaxKeys(1000);

        ListObjectsV2Result result = ossClient.listObjectsV2(req);

        // 使用 LinkedHashMap 保持分类的插入顺序
        Map<String, List<DocumentVO>> grouped = new LinkedHashMap<>();

        for (OSSObjectSummary summary : result.getObjectSummaries()) {
            String key = summary.getKey();
            // 只处理 PDF 文件
            if (!key.toLowerCase().endsWith(".pdf")) continue;

            // 截掉公共前缀后，格式为：分类名/文件名.pdf
            String relativePath = key.substring(prefix.length());
            int slashIdx = relativePath.indexOf('/');
            if (slashIdx < 0) continue; // 直接放在根前缀下的文件，跳过

            String category = relativePath.substring(0, slashIdx);
            String fileName  = relativePath.substring(slashIdx + 1);
            if (fileName.isEmpty()) continue; // 目录节点本身，跳过

            // 用 Base64 URL 安全编码 key，作为文档 ID 传给前端
            String id = Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(key.getBytes(StandardCharsets.UTF_8));

            grouped.computeIfAbsent(category, k -> new ArrayList<>())
                   .add(new DocumentVO(id, fileName, category, summary.getSize()));
        }

        return grouped;
    }

    /**
     * 根据文档 ID 生成预览和下载签名 URL
     * @param documentId Base64 URL 安全编码的 OSS key
     */
    public DocumentUrlVO generateSignedUrl(String documentId) throws Exception {
        String key = new String(
                Base64.getUrlDecoder().decode(documentId), StandardCharsets.UTF_8);
        String fileName = key.substring(key.lastIndexOf('/') + 1);

        Date expireDate = new Date(
                System.currentTimeMillis() + ossProperties.getSignUrlExpiration() * 1000L);

        // 预览 URL：不带 content-disposition，浏览器 inline 展示
        GeneratePresignedUrlRequest previewReq =
                new GeneratePresignedUrlRequest(ossProperties.getBucketName(), key, HttpMethod.GET);
        previewReq.setExpiration(expireDate);
        String previewUrl = ossClient.generatePresignedUrl(previewReq).toString();

        // 下载 URL：设置 content-disposition=attachment，浏览器强制下载
        GeneratePresignedUrlRequest downloadReq =
                new GeneratePresignedUrlRequest(ossProperties.getBucketName(), key, HttpMethod.GET);
        downloadReq.setExpiration(expireDate);
        ResponseHeaderOverrides headers = new ResponseHeaderOverrides();
        headers.setContentDisposition(
                "attachment;filename=" + URLEncoder.encode(fileName, StandardCharsets.UTF_8));
        downloadReq.setResponseHeaders(headers);
        String downloadUrl = ossClient.generatePresignedUrl(downloadReq).toString();

        return new DocumentUrlVO(documentId, fileName, previewUrl, downloadUrl);
    }

    /**
     * 按文献名模糊匹配文档（供 AI 对话引用使用）
     * 匹配策略：去掉书名号和 .pdf 后缀后做 contains 双向匹配（大小写不敏感）
     * @param referenceName 例如：急性缺血性脑卒中诊治指南2024 或 《急性缺血性脑卒中诊治指南》
     * @return 匹配到的文档 URL VO，未找到返回 null
     */
    public DocumentUrlVO matchByName(String referenceName) throws Exception {
        if (referenceName == null || referenceName.isBlank()) return null;

        // 去掉书名号、前后空格，转小写便于匹配
        String cleanName = normalize(referenceName.replaceAll("[《》]", "").trim());

        for (List<DocumentVO> docs : listDocuments().values()) {
            for (DocumentVO doc : docs) {
                // 去掉 .pdf 后缀后规范化再比较
                String docName = normalize(doc.getName().replaceAll("(?i)\\.pdf$", ""));
                if (docName.contains(cleanName) || cleanName.contains(docName)) {
                    return generateSignedUrl(doc.getId());
                }
            }
        }

        log.debug("[OSS] 文献名 '{}' 未在 OSS 中匹配到任何文档", referenceName);
        return null;
    }

    /**
     * 文献名规范化：统一同义词、去掉年份/版本数字、归并文体词、转小写
     * 目的是消除 AI 生成名称与 OSS 文件名之间的细微差异
     */
    private String normalize(String name) {
        return name
                .toLowerCase()
                .replace("脑卒中", "卒中")           // 统一"脑卒中"与"卒中"
                .replace("指南", "共识")              // 归并"指南/共识/规范"为统一词，减少歧义
                .replace("规范", "共识")
                .replaceAll("\\d+", "")              // 去掉所有数字（含非4位，如"第2版"中的2）
                .replaceAll("[（(][^）)]*[版本期年][）)]", "") // 去掉版本括号（如（2021年版））
                .replaceAll("第.{1,3}[版版期届]", "") // 去掉"第三版/第2期"等文本版本标记
                .replaceAll("[_（(）)\\s·•]", "");   // 去掉下划线、括号、空格、中英文点
    }
}
