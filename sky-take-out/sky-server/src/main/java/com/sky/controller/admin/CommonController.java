package com.sky.controller.admin;

import com.sky.constant.MessageConstant;
import com.sky.result.Result;
import com.sky.utils.AliOssUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/admin/common")
@Slf4j
public class CommonController {

    @Autowired
    private AliOssUtil aliOssUtil;

    // 允许上传的文件后缀白名单
    private static final List<String> ALLOWED_EXTENSIONS = Arrays.asList(".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp");

    /**
     * 上传文件
     * @param file
     * @return
     */
    @PostMapping("/upload")
    public Result<String> upload(MultipartFile file){
        log.info("上传文件：{}", file);

        try {
            // 原始文件名
            String originalFilename = file.getOriginalFilename();
            if (originalFilename == null || originalFilename.isEmpty()) {
                return Result.error("文件名不能为空");
            }

            // 截取文件后缀并转小写
            String extension = originalFilename.substring(originalFilename.lastIndexOf(".")).toLowerCase();

            // 校验文件后缀白名单
            if (!ALLOWED_EXTENSIONS.contains(extension)) {
                return Result.error("不支持的文件类型，仅允许：" + ALLOWED_EXTENSIONS);
            }

            // 构造新文件名
            String objectName = UUID.randomUUID().toString() + extension;

            // 上传文件到OSS
            String filePath = aliOssUtil.upload(file.getBytes(), objectName);

            return Result.success(filePath);
        } catch (IOException e) {
            log.error("上传文件失败：{}", e);
        }

        return Result.error(MessageConstant.UPLOAD_FAILED);
    }
}
