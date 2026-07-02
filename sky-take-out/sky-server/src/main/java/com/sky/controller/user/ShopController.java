package com.sky.controller.user;

import com.sky.result.Result;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.bind.annotation.*;

@RestController("userShopController")
@RequestMapping("/user/shop")
@Slf4j
public class ShopController {

    @Autowired
    private RedisTemplate redisTemplate;


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
