package com.sky.task;


import com.sky.entity.Orders;
import com.sky.mapper.OrderMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

@Component
@Slf4j
public class OrderTask {

    @Autowired
    private OrderMapper orderMapper;



    /**
     * 处理超时未支付订单
     */
    @Scheduled(cron = "30 * * * * ?")
//    @Scheduled(cron = "0/5 * * * * ?")
    public void processTimeoutOrder() {

        log.info("处理超时订单");
        List<Orders> orderList = orderMapper.getByStatusAndOrderTime(Orders.PENDING_PAYMENT, LocalDateTime.now().plusMinutes(-15));
        if(orderList != null && orderList.size() > 0) {

            orderList.forEach(order -> {
                order.setStatus(Orders.CANCELLED);
                order.setCancelReason("超时未支付");
                order.setCancelTime(LocalDateTime.now());
                orderMapper.update(order);
            });
        }
    }

    /**
     * 处理配送超时订单
     */
    @Scheduled(cron = "0 0 1 * *  ?")
    public void processDeliveryOrder() {
        log.info("处理配送超时订单");
        List<Orders> orderList = orderMapper.getByStatusAndOrderTime(Orders.DELIVERY_IN_PROGRESS, LocalDateTime.now().plusMinutes(-60));
        if(orderList != null && orderList.size() > 0) {

            orderList.forEach(order -> {
                order.setStatus(Orders.COMPLETED);
                orderMapper.update(order);
            });
        }

    }




}
