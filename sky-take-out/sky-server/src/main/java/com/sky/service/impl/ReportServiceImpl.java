package com.sky.service.impl;

import com.sky.dto.GoodsSalesDTO;
import com.sky.mapper.OrderDetailMapper;
import com.sky.mapper.OrderMapper;
import com.sky.mapper.UserMapper;
import com.sky.service.ReportService;
import com.sky.service.WorkspaceService;
import com.sky.vo.*;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang.StringUtils;
import org.apache.poi.xssf.usermodel.XSSFRow;
import org.apache.poi.xssf.usermodel.XSSFSheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import javax.servlet.ServletOutputStream;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.InputStream;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;



@Service
@Slf4j
public class ReportServiceImpl implements ReportService {

    @Autowired
    private OrderMapper orderMapper;

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private OrderDetailMapper orderDetailMapper;

    @Autowired
    private WorkspaceService workspaceService;

    @Override
    public TurnoverReportVO getTurnoverStatistics(LocalDate begin, LocalDate end) {
        List<LocalDate> dateList=new ArrayList<>();
        dateList.add(begin);
        while (!begin.equals(end)) {
            begin=begin.plusDays(1);
            dateList.add(begin);
        }

        List<Double> turnoverList=new ArrayList<>();
        for (LocalDate date : dateList) {
            //根据日期查询营业额
            LocalDateTime beginTime=LocalDateTime.of(date, LocalTime.MIN);
            LocalDateTime endTime=LocalDateTime.of(date, LocalTime.MAX);
            Map map=new HashMap<>();
            map.put("beginTime",beginTime);
            map.put("endTime",endTime);
            map.put("status",5);
            Double turnover= orderMapper.sumByMap(map);
            turnover=turnover==null?0.0:turnover;
            turnoverList.add(turnover);
        }

        //将日期列表转换为字符串，以逗号分隔
        String dateListStr= StringUtils.join(dateList,",");
        TurnoverReportVO turnoverReportVO = TurnoverReportVO
                .builder()
                .dateList(dateListStr)
                .turnoverList(StringUtils.join(turnoverList,","))
                .build();
        return turnoverReportVO;
    }

    /**
     * 用户数据统计
     */
    @Override
    public UserReportVO getUserStatistics(LocalDate begin, LocalDate end) {
        List<LocalDate> dateList = new ArrayList<>();
        dateList.add(begin);
        while (!begin.equals(end)) {
            begin = begin.plusDays(1);
            dateList.add(begin);
        }
        List<Integer> newUserList = new ArrayList<>();
        List<Integer> totalUserList = new ArrayList<>();
        for (LocalDate date : dateList) {
            //根据日期查询新增用户
            LocalDateTime beginTime = LocalDateTime.of(date, LocalTime.MIN);
            LocalDateTime endTime = LocalDateTime.of(date, LocalTime.MAX);
            Map map = new HashMap<>();
            map.put("endTime", endTime);
            Integer totalUser = userMapper.countByMap(map);
            map.put("beginTime", beginTime);
            Integer newUser = userMapper.countByMap(map);
            newUserList.add(newUser);
            totalUserList.add(totalUser);

        }

        //将日期列表转换为字符串，以逗号分隔
        String dateListStr = StringUtils.join(dateList, ",");
        //将新增用户列表转换为字符串，以逗号分隔
        String newUserListStr = StringUtils.join(newUserList, ",");
        //将用户总量列表转换为字符串，以逗号分隔
        String totalUserListStr = StringUtils.join(totalUserList, ",");

        UserReportVO userReportVO = UserReportVO
                .builder()
                .dateList(dateListStr)
                .newUserList(newUserListStr)
                .totalUserList(totalUserListStr)
                .build();
        return userReportVO;
    }

    /**
     * 订单数据统计
     */
    @Override
    public OrderReportVO getOrderStatistics(LocalDate begin, LocalDate end) {
        // 生成日期列表
        List<LocalDate> dateList = new ArrayList<>();
        dateList.add(begin);
        while (!begin.equals(end)) {
            begin = begin.plusDays(1);
            dateList.add(begin);
        }
        // 统计每天的订单数和有效订单数
        List<Integer> orderCountList = new ArrayList<>();
        List<Integer> validOrderCountList = new ArrayList<>();
        int totalOrderCount = 0;
        int validOrderCount = 0;
        for (LocalDate date : dateList) {
            LocalDateTime beginTime = LocalDateTime.of(date, LocalTime.MIN);
            LocalDateTime endTime = LocalDateTime.of(date, LocalTime.MAX);
            // 查询当天订单总数
            Map<String, Object> totalMap = new HashMap<>();
            totalMap.put("beginTime", beginTime);
            totalMap.put("endTime", endTime);
            Integer dayTotalOrder = orderMapper.countByMap(totalMap);
            dayTotalOrder = dayTotalOrder == null ? 0 : dayTotalOrder;
            // 查询当天有效订单数（状态为已完成）
            Map<String, Object> validMap = new HashMap<>();
            validMap.put("beginTime", beginTime);
            validMap.put("endTime", endTime);
            validMap.put("status", 5); // 5表示已完成
            Integer dayValidOrder = orderMapper.countByMap(validMap);
            dayValidOrder = dayValidOrder == null ? 0 : dayValidOrder;
            orderCountList.add(dayTotalOrder);
            validOrderCountList.add(dayValidOrder);
            totalOrderCount += dayTotalOrder;
            validOrderCount += dayValidOrder;
        }
        // 计算订单完成率
        double orderCompletionRate = 0.0;
        if (totalOrderCount > 0) {
            orderCompletionRate = Math.round(((double) validOrderCount / totalOrderCount) * 100) / 100.0;
        }
        // 构建返回结果
        OrderReportVO orderReportVO = OrderReportVO
                .builder()
                .dateList(StringUtils.join(dateList, ","))
                .totalOrderCount(totalOrderCount)
                .validOrderCount(validOrderCount)
                .orderCompletionRate(orderCompletionRate)
                .orderCountList(StringUtils.join(orderCountList, ","))
                .validOrderCountList(StringUtils.join(validOrderCountList, ","))
                .build();
        return orderReportVO;
    }

    /**
     * 销量排名top10
     */
    @Override
    public SalesTop10ReportVO getSalesTop10(LocalDate begin, LocalDate end) {
        LocalDateTime beginTime = LocalDateTime.of(begin, LocalTime.MIN);
        LocalDateTime endTime = LocalDateTime.of(end, LocalTime.MAX);

        // 查询销量排名top10的商品
        List<GoodsSalesDTO> salesTop10 = orderMapper.getSalesTop10(beginTime, endTime);
        //取出名字列表(stream流式处理)
        List<String> nameList = salesTop10.stream().map(GoodsSalesDTO::getName).collect(Collectors.toList());
        String nameListStr = StringUtils.join(nameList, ",");
        //取出销量列表
        List<Integer> numberList = salesTop10.stream().map(GoodsSalesDTO::getNumber).collect(Collectors.toList());
        String numberListStr = StringUtils.join(numberList, ",");
        SalesTop10ReportVO salesTop10ReportVO = SalesTop10ReportVO
                .builder()
                .nameList(nameListStr)
                .numberList(numberListStr)
                .build();
        return salesTop10ReportVO;
    }

    /**
     * 导出数据
     */
    @Override
    public void exportBusinessData(HttpServletResponse response) {

        LocalDate beginTime = LocalDate.now().minusDays(30);
        LocalDate endTime = LocalDate.now().minusDays(1);
        //1.查询数据库，获取营业数据
        BusinessDataVO businessDataVO = workspaceService
                .getBusinessData(LocalDateTime.of(beginTime, LocalTime.MIN), LocalDateTime.of(endTime, LocalTime.MAX));
        //2.通过poi将数据写入Excel中
        InputStream inputStream = this.getClass().getClassLoader().getResourceAsStream("template/运营数据报表模板.xlsx");

        try {
            //基于模板文件创建一个新的Excel文件
            XSSFWorkbook excel = new XSSFWorkbook(inputStream);
            //获取标签页Sheet1
            XSSFSheet sheet =  excel.getSheet("Sheet1");
            //获取第二行，填充数据————时间
            sheet.getRow(1).getCell(1).setCellValue("时间：" + beginTime + "至" + endTime);
            XSSFRow row = sheet.getRow(3);
            row.getCell(2).setCellValue(businessDataVO.getTurnover());
            row.getCell(4).setCellValue(businessDataVO.getOrderCompletionRate());
            row.getCell(6).setCellValue(businessDataVO.getNewUsers());
            row = sheet.getRow(4);
            row.getCell(2).setCellValue(businessDataVO.getValidOrderCount());
            row.getCell(4).setCellValue(businessDataVO.getUnitPrice());

            //填充明细数据
            for(int i = 0; i < 30; i++) {
                LocalDate date = beginTime.plusDays(i);
                BusinessDataVO dayBusinessDataVO = workspaceService.
                        getBusinessData(LocalDateTime.of(date, LocalTime.MIN), LocalDateTime.of(date, LocalTime.MAX));
                row = sheet.getRow(i + 7);
                row.getCell(1).setCellValue(date.toString());
                row.getCell(2).setCellValue(dayBusinessDataVO.getTurnover());
                row.getCell(3).setCellValue(dayBusinessDataVO.getValidOrderCount());
                row.getCell(4).setCellValue(dayBusinessDataVO.getOrderCompletionRate());
                row.getCell(5).setCellValue(dayBusinessDataVO.getUnitPrice());
                row.getCell(6).setCellValue(dayBusinessDataVO.getNewUsers());
            }

            //3.通过输出流将Excel文件下载到浏览器
            ServletOutputStream outputStream = response.getOutputStream();
            excel.write(outputStream);

            //关闭资源
            outputStream.close();
            excel.close();
        } catch (IOException e) {
            throw new RuntimeException(e);
        }


    }


}
