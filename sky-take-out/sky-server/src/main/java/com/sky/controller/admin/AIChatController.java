package com.sky.controller.admin;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sky.dto.AIChatRequest;
import com.sky.result.Result;
import com.sky.vo.AIChatResponse;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@RestController("adminAIChatController")
@RequestMapping("/admin/ai")
@Api(tags = "AI 智能客服")
@Slf4j
public class AIChatController {

    @Value("${sky.ai.agent-url:http://localhost:8000}")
    private String agentUrl;

    private final RestTemplate restTemplate = new RestTemplate();
    private final ObjectMapper objectMapper = new ObjectMapper();

    // 流式请求专用线程池，最多 16 个并发线程
    private final ExecutorService streamExecutor = Executors.newFixedThreadPool(16,
            r -> new Thread(r, "ai-stream-" + r.hashCode()));

    /**
     * AI 客服对话（同步接口，兼容旧前端）
     */
    @PostMapping("/chat")
    @ApiOperation("AI 客服对话")
    public Result<AIChatResponse> chat(@RequestBody AIChatRequest request) {
        log.info("AI客服请求：{}", request.getQuery());

        String url = agentUrl + "/chat";
        Map<String, Object> response = restTemplate.postForObject(
                url,
                request,
                Map.class
        );

        String reply = (String) response.get("response");
        log.info("AI客服回复：{}", reply);
        return Result.success(new AIChatResponse(reply));
    }

    /**
     * AI 客服对话（SSE 流式接口）
     * 将用户消息转发到 Python Agent 的 /chat/stream 端点，
     * 以 Server-Sent Events 格式逐 token 推送到前端
     * @param request 包含用户消息和历史记录的请求体
     * @return SSE 流式推送器
     */
    @PostMapping(value = "/chat/stream", produces = "text/event-stream;charset=UTF-8")
    @ApiOperation("AI 客服对话（流式）")
    public SseEmitter chatStream(@RequestBody AIChatRequest request) {
        log.info("AI客服流式请求：{}", request.getQuery());

        // 创建 SseEmitter，超时 3 分钟
        SseEmitter emitter = new SseEmitter(180_000L);

        // 后台线程：从 Python Agent 流式读取并转发到前端
        streamExecutor.execute(() -> {
            HttpURLConnection conn = null;
            try {
                URL url = new URL(agentUrl + "/chat/stream");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setDoOutput(true);
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(0); // 读超时无限（流式）

                // 序列化请求体并写入
                objectMapper.writeValue(conn.getOutputStream(), request);

                int statusCode = conn.getResponseCode();
                if (statusCode != 200) {
                    emitter.completeWithError(
                            new RuntimeException("Agent 服务返回异常状态码: " + statusCode));
                    return;
                }

                // 逐行读取 Python SSE 事件并转发
                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (line.startsWith("data: ")) {
                            String data = line.substring(6).trim();
                            if ("[DONE]".equals(data)) {
                                // 流结束
                                emitter.complete();
                                return;
                            }
                            // 解析 token 值，通过 Jackson 序列化 Map 以 UTF-8 编码输出
                            try {
                                @SuppressWarnings("unchecked")
                                Map<String, String> parsed = objectMapper.readValue(data, Map.class);
                                String tokenValue = parsed.get("token");
                                if (tokenValue != null) {
                                    Map<String, String> out = new HashMap<>();
                                    out.put("token", tokenValue);
                                    emitter.send(SseEmitter.event().data(out));
                                }
                            } catch (Exception e) {
                                log.warn("解析 SSE 数据失败: {}", data);
                            }
                        }
                    }
                    emitter.complete();
                }
            } catch (Exception e) {
                log.error("SSE 流式代理出错", e);
                emitter.completeWithError(e);
            } finally {
                if (conn != null) {
                    conn.disconnect();
                }
            }
        });

        return emitter;
    }
}
