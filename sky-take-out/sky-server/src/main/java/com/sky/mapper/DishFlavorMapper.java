package com.sky.mapper;


import com.sky.entity.DishFlavor;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface DishFlavorMapper {
    /**
     * 批量插入菜品口味数据
     * @param flavors
     */
    void insertBatch(List<DishFlavor> flavors);
    /**
     * 根据菜品id删除菜品口味数据
     * @param dishid
     */
    @Delete("delete from dish_flavor where dish_id = #{id}")
    void deleteByDishIds(Long dishid);
     /**
      * 优化后批量删除菜品口味数据
      * @param ids
      */
    void deleteBatchByDishIds(List<Long> ids);

    /**
     * 根据菜品id查询菜品口味数据
     * @param dishid
     * @return
     */
    @Select("select * from dish_flavor where dish_id = #{dishid}")
    List<DishFlavor> getByDishId(Long dishid);
}
