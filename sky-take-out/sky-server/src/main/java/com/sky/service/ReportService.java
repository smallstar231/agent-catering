package com.sky.service;

import com.sky.vo.OrderReportVO;
import com.sky.vo.SalesTop10ReportVO;
import com.sky.vo.TurnoverReportVO;
import com.sky.vo.UserReportVO;

import javax.servlet.http.HttpServletResponse;
import java.time.LocalDate;

public interface ReportService {

    /**
     * 营业额数据统计
     */
    TurnoverReportVO getTurnoverStatistics(LocalDate begin, LocalDate end);

    /**
     * 用户数据统计
     */
    UserReportVO getUserStatistics(LocalDate begin, LocalDate end);

    /**
     * 订单数据统计
     */
    OrderReportVO getOrderStatistics(LocalDate begin, LocalDate end);
    /**
      * 销量排名top10
     */
    SalesTop10ReportVO getSalesTop10(LocalDate begin, LocalDate end);

    /**
     *
     * @param response
     */
    void exportBusinessData(HttpServletResponse response);
}
