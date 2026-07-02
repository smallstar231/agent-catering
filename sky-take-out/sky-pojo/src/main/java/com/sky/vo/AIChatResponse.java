package com.sky.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;

import java.io.Serializable;

@Data
@AllArgsConstructor
@ApiModel(description = "AI 客服对话响应")
public class AIChatResponse implements Serializable {

    @ApiModelProperty("AI 回复内容")
    private String response;
}
