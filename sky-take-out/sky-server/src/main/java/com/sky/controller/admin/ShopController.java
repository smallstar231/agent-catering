package com.sky.controller.admin;

import com.sky.result.Result;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.bind.annotation.*;

@RestController("adminShopController")
@RequestMapping("/admin/shop")
@Slf4j
public class ShopController {

    @Autowired
    private RedisTemplate redisTemplate;

    /**
     * 设置店铺状态
     * @param status 店铺状态，1为营业，0为关闭
     * @return 结果对象
     */
    @PutMapping("/{status}")
    public Result setStatus(@PathVariable Integer status) {
        log.info("设置店铺状态为：{}", status);
        // 店铺状态缓存到Redis中
        redisTemplate.opsForValue().set("shop_status", status);
        return Result.success();
    }

    /**
     * 获取店铺状态
     * @return 店铺状态，1为营业，0为关闭
     */
    @GetMapping("/status")
    public Result<Integer> getStatus() {
        Integer status = (Integer) redisTemplate.opsForValue().get("shop_status");
        log.info("店铺状态为：{}", status);
        return Result.success(status);
    }
}
