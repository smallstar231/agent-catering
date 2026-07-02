package com.sky.controller.admin;

import com.sky.result.Result;
import com.sky.service.ReportService;
import com.sky.vo.OrderReportVO;
import com.sky.vo.SalesTop10ReportVO;
import com.sky.vo.TurnoverReportVO;
import com.sky.vo.UserReportVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.LocalDate;

@RestController
@RequestMapping("/admin/report")
@Slf4j
public class ReportController {

    @Autowired
    private ReportService reportService;

    /**
     * 营业额数据统计
     */
    @GetMapping("/turnoverStatistics")
    public Result<TurnoverReportVO> turnoverStatistics
            (@DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate begin,
            @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate end) {
        log.info("营业额数据统计，begin: {}, end: {}", begin, end);
        TurnoverReportVO turnoverReportVO = reportService.getTurnoverStatistics(begin, end);
        return Result.success(turnoverReportVO);
    }


    /**
     * 用户数据统计
     */
    @GetMapping("/userStatistics")
    public Result<UserReportVO> userStatistics
            (@DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate begin,
            @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate end) {
        log.info("用户数据统计，begin: {}, end: {}", begin, end);
        return Result.success(reportService.getUserStatistics(begin, end));
    }

    /**
     * 订单数据统计
     */
    @GetMapping("/ordersStatistics")
    public Result<OrderReportVO> ordersStatistics
    (@DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate begin,
     @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate end) {
        log.info("订单数据统计，begin: {}, end: {}", begin, end);
        return Result.success(reportService.getOrderStatistics(begin, end));
    }

    /**
     * 销量排名top10
     */
    @GetMapping("/top10")
    public Result<SalesTop10ReportVO> top10
    (@DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate begin,
     @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate end) {
        log.info("销量排名top10，begin: {}, end: {}", begin, end);
        return Result.success(reportService.getSalesTop10(begin, end));
    }
    /**
     * 导出数据
     */
    @GetMapping("/export")
    public void export(HttpServletResponse response) {
        reportService.exportBusinessData(response);
    }


}
