package com.sky.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.io.Serializable;
import java.util.List;

@Data
@ApiModel(description = "AI 客服对话请求")
public class AIChatRequest implements Serializable {

    @ApiModelProperty("用户消息")
    private String query;

    @ApiModelProperty("历史消息列表")
    private List<ChatMessage> history;

    @Data
    @ApiModel(description = "单条聊天消息")
    public static class ChatMessage implements Serializable {

        @ApiModelProperty("角色：user 或 assistant")
        private String role;

        @ApiModelProperty("消息内容")
        private String content;
    }
}
