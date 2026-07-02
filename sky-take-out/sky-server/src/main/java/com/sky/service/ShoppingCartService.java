package com.sky.service;

import com.sky.dto.ShoppingCartDTO;
import com.sky.entity.ShoppingCart;

import java.util.List;

public interface ShoppingCartService {
    /**
     * 添加商品到购物车
     * @param shoppingCartDTO
     * @return
     */
    void addShoppingCart(ShoppingCartDTO shoppingCartDTO);

    /**
     * 查询购物车列表
     * @return
     */
    List<ShoppingCart> showShoppingCart();


    /**
     * 清空购物车
     * @return
     */
    void clean();

    /**
     * 删除购物车商品
     * @param shoppingCartDTO
     * @return
     */
    void deleteShoppingCart(ShoppingCartDTO shoppingCartDTO);
}
