package com.sky.service.impl;

import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import com.sky.constant.MessageConstant;
import com.sky.constant.StatusConstant;
import com.sky.dto.DishDTO;
import com.sky.dto.DishPageQueryDTO;
import com.sky.entity.Dish;
import com.sky.entity.DishFlavor;
import com.sky.exception.DeletionNotAllowedException;
import com.sky.mapper.DishFlavorMapper;
import com.sky.mapper.DishMapper;
import com.sky.result.PageResult;
import com.sky.service.DishService;
import com.sky.vo.DishVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;

import static com.sky.constant.StatusConstant.ENABLE;
import com.sky.mapper.SetmealDishMapper;

@Service
@Slf4j
public class DishServiceImpl implements DishService {

    @Autowired
    private DishMapper dishMapper;

    @Autowired
    private DishFlavorMapper dishFlavorMapper;

    @Autowired
    private SetmealDishMapper setmealDishMapper;

    /**
     * 新增菜品和对应的口味数据
     * @param dishDTO
     */
    @Transactional
    public void savewithFlavor(DishDTO dishDTO) {

        Dish dish = new Dish();
        BeanUtils.copyProperties(dishDTO, dish);
        //向菜品表插入一条数据
        dishMapper.insert(dish);

        //获取新插入的菜品的id
        Long id=dish.getId();
        //向口味表插入n条数据
        List<DishFlavor> flavors = dishDTO.getFlavors();
        if (flavors != null && flavors.size() > 0) {

            flavors.forEach(flavor -> {
                flavor.setDishId(id);
            });

            dishFlavorMapper.insertBatch(flavors);
        }



    }

    /**
     * 分页查询菜品
     * @param dishPageQueryDTO
     * @return
     */
    public PageResult pageQuery(DishPageQueryDTO dishPageQueryDTO) {
        PageHelper.startPage(dishPageQueryDTO.getPage(), dishPageQueryDTO.getPageSize());
        Page<DishVO> page = dishMapper.pageQuery(dishPageQueryDTO);
        return new PageResult(page.getTotal(), page.getResult());
    }

    /**
     * 删除菜品
     * @param ids
     * @return
     */
    @Override
    @Transactional
    public void deleteBatch(List<Long> ids) {
          //优化前
//        //判断当前菜品能否删除--是否正在销售中
//        ids.forEach(id -> {
//            Dish dish = dishMapper.getById(id);
//            if (dish.getStatus().equals(ENABLE)) {
//                throw new DeletionNotAllowedException(MessageConstant.DISH_ON_SALE);
//            }
//        });

        // 优化后（一次批量查询）
        List<Dish> dishes = dishMapper.getByIds(ids);
        for (Dish dish : dishes) {
            if (dish.getStatus().equals(ENABLE)) {
                throw new DeletionNotAllowedException(MessageConstant.DISH_ON_SALE);
            }
        }

        //判断当前菜品能否删除--是否套餐关联了
        List<Long> setmealIds = setmealDishMapper.getSetmealIdsByDishIds(ids);
        if (setmealIds != null && setmealIds.size() > 0) {
                throw new DeletionNotAllowedException(MessageConstant.DISH_BE_RELATED_BY_SETMEAL);
        }

//        //优化前
//        //删除菜品表中的数据
//        ids.forEach(id -> {
//            dishMapper.deleteByid(id);
//            //删除口味表中关联的数据
//            dishFlavorMapper.deleteByDishIds(id);
//        });

        // 优化后（批量删除）
        dishMapper.deleteBatchByIds(ids);
        dishFlavorMapper.deleteBatchByDishIds(ids);


    }

    /**
     * 根据id查询菜品
     * @param id
     * @return
     */
    @Override
    public DishVO getByIdWithFlavor(Long id) {

        //根据id查询菜品
        Dish dish = dishMapper.getById(id);
        //根据id查询菜品口味
        List<DishFlavor> flavors = dishFlavorMapper.getByDishId(id);
        //将查询到的菜品和口味封装到DishVO中
        DishVO dishVO = new DishVO();
        BeanUtils.copyProperties(dish, dishVO);
        dishVO.setFlavors(flavors);
        return dishVO;
    }

        /**
         * 更新菜品和对应的口味数据
         * @param dishDTO
         */
    @Override
    public void updateWithFlavor(DishDTO dishDTO) {

        //修改菜品表基本信息
        Dish dish = new Dish();
        BeanUtils.copyProperties(dishDTO, dish);
        dishMapper.update(dish);

        //删除原有的口味数据
        dishFlavorMapper.deleteByDishIds(dishDTO.getId());

        //插入新的口味数据
        List<DishFlavor> flavors = dishDTO.getFlavors();
        if (flavors != null && flavors.size() > 0) {

            flavors.forEach(flavor -> {
                flavor.setDishId(dishDTO.getId());
            });

            dishFlavorMapper.insertBatch(flavors);

        }
    }

    /**
     * 根据分类id查询菜品
     * @param categoryId
     * @return
     */
    @Override
    public List<Dish> list(Long categoryId) {
        Dish dish = Dish.builder()
                .categoryId(categoryId)
                .status(StatusConstant.ENABLE)
                .build();
        return dishMapper.list(dish);
    }

        /**
         * 起售/停售菜品
         * @param status
         * @param id
         */
    @Override
    public void updateStatus(Integer status, Long id) {
        Dish dish = Dish.builder()
                .id(id)
                .status(status)
                .build();
        dishMapper.update(dish);
    }

    /**
     * 条件查询菜品和口味
     * @param dish
     * @return
     */
    public List<DishVO> listWithFlavor(Dish dish) {
        List<Dish> dishList = dishMapper.list(dish);

        List<DishVO> dishVOList = new ArrayList<>();

        for (Dish d : dishList) {
            DishVO dishVO = new DishVO();
            BeanUtils.copyProperties(d,dishVO);

            //根据菜品id查询对应的口味
            List<DishFlavor> flavors = dishFlavorMapper.getByDishId(d.getId());

            dishVO.setFlavors(flavors);
            dishVOList.add(dishVO);
        }

        return dishVOList;
    }
}
