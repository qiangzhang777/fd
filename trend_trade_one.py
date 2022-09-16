# !/usr/bin python3
# -*- encoding:utf-8 -*-
# @Author : Samzhang
# @File : etf1.11.py
# @Time : 2022/1/11 6:56

import requests as req
import httpx
import asyncio
import re
import pandas as pd
import time
import tushare as ts
import pymongo as pm
from multiprocessing import Process
from multiprocessing import Queue
import pyautogui as pg
from selenium import webdriver
import tkinter as tk
import math
import random
import os
import datetime
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from proxy_url import Proxy_url
from logger import *
import threading as thr
from auto_login import *
import json
import talib
import numpy
from send_2_phone import *


class Trend:
    def __init__(self, today, yestoday):

        # 设置交易时间
        self.today = today
        self.yestoday = yestoday

        # 连接mongoDB
        self.myclient = pm.MongoClient("mongodb://localhost:27017/")
        self.fd = self.myclient["freedom"]

        self.trend_rec = self.fd['trend_rec']

        self.hasBuy = self.fd['trend_has_buy']

        self.basic_data_store = self.fd['trend__basic_data']

        self.all_trend_df = pd.read_excel('./find_trend/k_daily/000trend_k_list.xlsx')
        print(self.all_trend_df['ts_code'].values)
        self.all_jk_buy_df = pd.read_excel('./find_trend/k_daily/000jk_buy_list.xlsx')
        print(self.all_jk_buy_df['ts_code'].values)
        # 新出现底部
        self.all_jk_list = [self.chg_code_type(str(code).zfill(6)) for code in self.all_jk_buy_df['ts_code'].values]
        print(self.all_jk_list)

        self.all_jk_buy_list = self.all_jk_list
        self.all_jk_sale_list = []
        # 加入未卖出标的
        for r in self.trend_rec.find({'isSold': 0}):
            self.all_jk_sale_list.append(r['code'])
            self.all_jk_list.append(r['code'])
            if r['code'] in self.all_jk_buy_list:
                self.all_jk_buy_list.remove(r['code'])

        self.trend_reality = self.fd['trend_reality']

        # 启动日志
        file_name = str(os.path.basename(__file__).split('.')[0])
        # self.logger = Logger('./trading_' + str(self.today) + '.log').get_logger()
        self.logger = self.getlogger()

        # 创建selenium句柄
        self.trader = Auto_trade(False)

        # 设置ip池
        self.ipPool = self.fd['ipPool']
        self.allIpPool = self.fd['allIpPool']

        # 捕捉最低和最高价格临时记录字典变量
        self.catch_lowest = {}
        self.catch_highest = {}
        self.code_ma = {}
        # 临时存储极值
        self.lowest_price = {}
        self.highest_price = {}
        # 记录清空标记
        self.clean_flag = {}

        # 获取当日交易的股票代码
        for j in self.all_jk_list:
            self.catch_lowest[j] = pd.Series(dtype='float64')
            self.catch_highest[j] = pd.Series(dtype='float64')

            # 临时存储极值
            # 临时记录当日最低价格和最高价格
            self.lowest_price[j] = 1000
            self.highest_price[j] = 0

            # 记录清空标记
            self.clean_flag[j] = False

            # 获取所有code的均线ma数据
            self.code_ma[j] = self.get_ma(j)
            print(j, self.code_ma[j]['beili'], self.code_ma[j]['trd_days'], self.code_ma[j]['trend3'])

        # exit()
        # 初始话ser和lastreq
        self.ser = pd.Series(dtype='float64')
        self.lastreq = {}

        self.isAppear_top = {}

        # 设置最大仓位
        self.total_yingkui_money = 0
        yingkui_res = self.trend_rec.find()
        if yingkui_res:
            for r in yingkui_res:
                self.total_yingkui_money += r['yingkui']

        self.logger.info(f"total_yingkui_money:{self.total_yingkui_money}")
        self.trends_top_money = 60000 + int(self.total_yingkui_money / 1000) * 1000
        self.per_top_money = self.trends_top_money / 40

        self.trade_lock = thr.Lock()

        self.pct_sh = 0
        self.pct_sz = 0

    def getlogger(self):
        self.logger = logging.getLogger("logger")
        # 判断是否有处理器，避免重复执行
        if not self.logger.handlers:
            # 日志输出的默认级别为warning及以上级别，设置输出info级别
            self.logger.setLevel(logging.DEBUG)
            # 创建一个处理器handler  StreamHandler()控制台实现日志输出
            sh = logging.StreamHandler()
            # 创建一个格式器formatter  （日志内容：当前时间，文件，日志级别，日志描述信息）
            formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(lineno)d line]: %(message)s')

            # 创建一个文件处理器，文件写入日志
            fh = logging.FileHandler(filename='./trading_' + str(self.today) + '.log', encoding="utf8")
            # 创建一个文件格式器f_formatter
            f_formatter = logging.Formatter(fmt="[%(asctime)s] [%(levelname)s] [%(lineno)d line]: %(message)s", datefmt="%Y/%m/%d %H:%M:%S")

            # 关联控制台日志器—处理器—格式器
            self.logger.addHandler(sh)
            sh.setFormatter(formatter)
            # 设置处理器输出级别
            sh.setLevel(logging.DEBUG)

            # 关联文件日志器-处理器-格式器
            self.logger.addHandler(fh)
            fh.setFormatter(f_formatter)
            # 设置处理器输出级别
            fh.setLevel(logging.DEBUG)

        return self.logger

    # 保持登录
    def keep_login(self):
        time.sleep(30)
        while True:
            time.sleep(1)
            curr_time = datetime.datetime.now()

            # 9点10分，12点40退出重新登录
            # if curr_time.hour == 9 and curr_time.minute == 15 and curr_time.second == 10:
            #     try:
            #         is_login = self.trader.wait.until(EC.text_to_be_present_in_element((By.XPATH, '//*[@id="main"]/div/div[1]/p/span[2]/a'), '退出'))
            #
            #         if is_login:
            #             self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[1]/p/span[2]/a').click()
            #             # send_notice('logout_auto:', f"{curr_time}")
            #             time.sleep(10)
            #     except Exception as e:
            #         self.logger.error(f"logout_fail：{curr_time}, {e}")
            # elif curr_time.hour == 12 and curr_time.minute == 40 and curr_time.second == 10:
            #     try:
            #         is_login = self.trader.wait.until(EC.text_to_be_present_in_element((By.XPATH, '//*[@id="main"]/div/div[1]/p/span[2]/a'), '退出'))
            #
            #         if is_login:
            #             self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[1]/p/span[2]/a').click()
            #             # send_notice('logout_auto:', f"{curr_time}")
            #             time.sleep(10)
            #     except Exception as e:
            #         self.logger.error(f"logout_fail：{curr_time}, {e}")

            # 每隔20秒检查是否登录
            try:
                if curr_time.minute % 59 == 0 and curr_time.second % 59 == 0:
                    res = self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[2]/div[1]/ul/li[1]/a').click()
                    time.sleep(10)
                    self.logger.info(f"login_state:alive, {curr_time}, {res}")  # send_notice('login_state', f"alive, {curr_time}, {res}")
                elif curr_time.minute % 59 == 0 and curr_time.second % 58 == 0:
                    res = self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[2]/div[1]/ul/li[2]/a').click()
                    time.sleep(10)
                    self.logger.info(f"login_state:alive, {curr_time}, {res}")  # send_notice('login_state', f"alive, {curr_time}, {res}")
                elif curr_time.minute % 59 == 0 and curr_time.second % 57 == 0:
                    res = self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[2]/div[1]/ul/li[3]/a').click()
                    time.sleep(10)
                    self.logger.info(f"login_state:alive, {curr_time}, {res}")  # send_notice('login_state', f"alive, {curr_time}, {res}")
                elif curr_time.minute % 59 == 0 and curr_time.second % 56 == 0:
                    res = self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[2]/div[1]/ul/li[4]/a').click()
                    time.sleep(10)
                    self.logger.info(f"login_state:alive, {curr_time}, {res}")  # send_notice('login_state', f"alive, {curr_time}, {res}")
            except Exception as e:
                self.logger.error(f"登录失效：{curr_time}, {e}")
                # send_notice('login_state', f"lost, {curr_time}, {e}")
                self.trader.login()
                try:
                    res = self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[2]/div[1]/ul/li[1]/a').click()  # send_notice('login_state', f"alive_agin, {curr_time}, {res}")
                except Exception as e:
                    self.logger.error(f"重新登录失败：{curr_time}, {e}")
                    # send_notice('login_state', f"lost_agin, {curr_time}, {e}")
                    self.trader.login()

            if curr_time.hour == 12 and curr_time.minute == 50 and curr_time.second >= 57:
                # self.trader.login()
                self.trader = Auto_trade(False)
                time.sleep(5)

            if curr_time.hour >= 15 and curr_time.minute > 3:
                break

    # 修改代码类型
    def chg_code_type(self, code):
        if code[7:9] == 'SZ':
            code = 'sz' + code[0:6]
        elif code[7:9] == 'SH':
            code = 'sh' + code[0:6]
        elif code[0] == '0':
            code = 'sz' + code[0:6]
        elif code[0] == '6':
            code = 'sh' + code[0:6]
        return code

    # 获取基础成交数据
    def get_basic_data(self):
        id = 1
        while True:
            # 每秒获取逐笔交易数据
            curr_time = datetime.datetime.now()
            if curr_time.hour >= 9 and curr_time.hour <= 15:
                if (curr_time.hour == 11 and curr_time.minute > 30) or curr_time.hour == 12:
                    continue
                elif curr_time.hour >= 15 and curr_time.minute > 3:
                    break
                elif (curr_time.hour == 9 and curr_time.minute >= 30) or curr_time.hour >= 10:
                    # if 1:
                    #     if 1:
                    try:
                        ncode = []
                        lastreq = {}
                        for c in self.all_jk_list:
                            # print(c)
                            ncode.append(self.chg_code_type(c))
                        all_list_2str = ','.join(ncode)

                        url = "https://qt.gtimg.cn/q=" + all_list_2str + "&r=926277345"
                        # print(url)

                        try:
                            res = Proxy_url.urlget(url)  # print(res)
                        except Exception as e:
                            self.logger.error(e)  # raise e
                        else:
                            res = re.split(";", res.text)
                            # print('res:',res)
                            ser = pd.Series(dtype='float64')
                            # 移除尾巴上的/n
                            res.pop()
                            for r in res:
                                info = re.split('~', r)
                                # 修改etf代码号，前面加上sz或者sh
                                for c in self.all_jk_list:
                                    if info[2] in c:
                                        info[2] = c
                                # 存入当次访问的基础info数据
                                lastreq[info[2]] = info
                                # 存入个股实时价格，并在后面对比最低价格
                                ser[info[2]] = float(info[3])  # print(lastreq)  # print(ser)

                    except Exception as e:
                        self.logger.error('error1' + str(e))
                        # raise e

                    else:
                        # 将基础数据存入mongog
                        self.basic_data2mongo(id, curr_time, ser, lastreq)
                        self.ser = ser
                        self.lastreq = {}

                        for code, per in lastreq.items():
                            self.lastreq[code] = {}
                            self.lastreq[code]['name'] = per[1]
                            self.lastreq[code]['curr_price'] = float(per[3])
                            self.lastreq[code]['today_highest'] = float(per[33])
                            self.lastreq[code]['today_lowest'] = float(per[34])
                            self.lastreq[code]['pct_chg'] = float(per[32])
                            self.lastreq[code]['yestoday_close'] = float(per[4])
                            self.lastreq[code]['today_open'] = float(per[5])

                        id += 1

            if  curr_time.minute % 25 == 0 and curr_time.second % 59 == 0:
                print('get_basic_data is alive:', curr_time.time(), len(self.ser))

            if curr_time.hour >= 15 and curr_time.minute >= 2:
                break

            time.sleep(1)

    def basic_data2mongo(self, id, curr_time, ser, lastreq):
        data = {}
        data['id'] = id
        data['date'] = self.today
        data['curr_time'] = str(curr_time)
        data['ser'] = str(ser)
        data['lastreq'] = str(lastreq)
        self.basic_data_store.insert_one(data)

    def dp(self):
        while True:
            # 每秒获取逐笔交易数据
            curr_time = datetime.datetime.now()
            if curr_time.hour >= 9 and curr_time.hour <= 15:
                if (curr_time.hour == 11 and curr_time.minute > 30) or curr_time.hour == 12:
                    continue
                elif curr_time.hour >= 15 and curr_time.minute > 3:
                    break
                elif (curr_time.hour == 9 and curr_time.minute >= 25) or curr_time.hour >= 10:
                    # 获取当日两市上涨概况
                    url = 'http://qt.gtimg.cn/?q=s_sz399001,s_sz399300,s_sh000016,s_sz399004,bkqtRank_A_sh,bkqtRank_B_sh,bkqtRank_A_sz,bkqtRank_B_sz&_=1595790947726'
                    res = req.get(url)
                    res = re.split(';', res.text)
                    sh = re.split('~', res[4])
                    sz = re.split('~', res[6])
                    # 获取沪市上涨的股票
                    sh_url = 'http://stock.gtimg.cn/data/view/rank.php?t=rankash/chr&p=1&o=0&l=' + str(int(sh[2])) + '&v=list_data'
                    sh_res = req.get(sh_url)
                    sh_res = re.split("'", sh_res.text)
                    sh_res = re.split(',', sh_res[3])

                    # 获取深市上涨的股票
                    sz_url = 'http://stock.gtimg.cn/data/view/rank.php?t=rankasz/chr&p=1&o=0&l=' + str(int(sz[2])) + '&v=list_data'
                    sz_res = req.get(sz_url)
                    sz_res = re.split("'", sz_res.text)
                    sz_res = re.split(',', sz_res[3])
                    codelist2 = sh_res + sz_res

                    # 获取红盘占比，得到市场的情绪
                    all_sh = 1951
                    all_sz = 2469

                    self.pct_sh = len(sh_res) / all_sh
                    self.pct_sz = len(sz_res) / all_sz

                    # return pct_sh,pct_sz

            if curr_time.hour >= 15 and curr_time.minute >= 1:
                break

            time.sleep(1)

    def get_ma(self, code):
        # 获取历史交易的收盘价，最高价格，最低价，用于计算均价
        self.code_df = self.all_trend_df[self.all_trend_df['ts_code'] == code]
        # print(self.code_df)
        ma_dict = {}
        ma_dict['beili'] = self.code_df['beili'].values[0]
        ma_dict['trd_days'] = self.code_df['trd_days'].values[0]

        ma_dict['sum_ma4'] = self.code_df['sum4'].values[0]
        ma_dict['sum_ma5'] = self.code_df['sum5'].values[0]
        ma_dict['sum_ma6'] = self.code_df['sum6'].values[0]
        ma_dict['sum_ma7'] = self.code_df['sum7'].values[0]
        ma_dict['sum_ma8'] = self.code_df['sum8'].values[0]
        ma_dict['yes2_ma5'] = self.code_df['yes2_ma5'].values[0]
        ma_dict['yes1_ma5'] = self.code_df['yes1_ma5'].values[0]
        ma_dict['yes1_ma4'] = self.code_df['yes1_ma4'].values[0]
        ma_dict['yes2_ma4'] = self.code_df['yes2_ma4'].values[0]
        ma_dict['yes1_ma6'] = self.code_df['yes1_ma6'].values[0]
        ma_dict['yes2_ma6'] = self.code_df['yes2_ma6'].values[0]
        ma_dict['yes1_ma7'] = self.code_df['yes1_ma7'].values[0]
        ma_dict['yes2_ma7'] = self.code_df['yes2_ma7'].values[0]
        ma_dict['yes1_ma8'] = self.code_df['yes1_ma8'].values[0]
        ma_dict['yes2_ma8'] = self.code_df['yes2_ma8'].values[0]
        ma_dict['yes1_close'] = self.code_df['yes1_close'].values[0]
        ma_dict['yes2_close'] = self.code_df['yes2_close'].values[0]
        ma_dict['yes1_lowest'] = self.code_df['yes1_lowest'].values[0]
        ma_dict['yes2_lowest'] = self.code_df['yes2_lowest'].values[0]
        ma_dict['yes1_highest'] = self.code_df['yes1_highest'].values[0]
        ma_dict['yes2_highest'] = self.code_df['yes2_highest'].values[0]

        ma_dict['yes1_macd'] = self.code_df['yes1_macd'].values[0]
        ma_dict['yes2_macd'] = self.code_df['yes2_macd'].values[0]

        ma_dict['trend3'] = self.code_df['trend3'].values[0]
        ma_dict['trend4'] = self.code_df['trend4'].values[0]
        ma_dict['trend5'] = self.code_df['trend5'].values[0]
        ma_dict['trend6'] = self.code_df['trend6'].values[0]

        ma_dict['trend8'] = self.code_df['trend8'].values[0]
        ma_dict['trend9'] = self.code_df['trend9'].values[0]
        ma_dict['trend10'] = self.code_df['trend10'].values[0]

        ma_dict['trend12'] = self.code_df['trend12'].values[0]
        ma_dict['trend13'] = self.code_df['trend13'].values[0]
        ma_dict['trend14'] = self.code_df['trend14'].values[0]

        ma_dict['trend20'] = self.code_df['trend20'].values[0]
        ma_dict['trend50'] = self.code_df['trend50'].values[0]

        return ma_dict

    def jk_buy(self):
        while True:
            curr_time = datetime.datetime.now()
            ser = self.ser
            lastreq = self.lastreq

            if curr_time.minute % 25 == 0 and curr_time.second % 59 == 0:
                print('jk_buy is alive:', curr_time.time(), len(self.ser))

            if curr_time.hour >= 9 and curr_time.hour <= 15:

                if (curr_time.hour == 11 and curr_time.minute > 30) or curr_time.hour == 12:
                    continue
                elif (curr_time.hour == 9 and curr_time.minute >= 30) or curr_time.hour >= 10:

                    for k, v in ser.iteritems():
                        # self.logger.debug('*' * 100)
                        # 如果标的不在jk_buy_list里面，那么跳过
                        if k not in self.all_jk_buy_list:
                            continue

                        if k in self.all_jk_sale_list:
                            continue

                        try:
                            # 数据记录
                            # ---------------------------------------------------------------------------------------
                            # 判断当前价格是否低于最低价格，如果低于最低价格，那么清空该字典，然后再插入最低价,并从最低价开始记录
                            try:
                                today_lowest = lastreq[k]['today_lowest']
                                curr_price = lastreq[k]['curr_price']
                            except Exception as e:
                                self.logger.error(f"lastreq:{lastreq}, {e}")
                            # 捕捉最小值，跟踪反弹
                            try:
                                if self.lowest_price[k] > today_lowest:
                                    self.lowest_price[k] = today_lowest
                                    self.catch_lowest[k] = pd.Series(dtype='float64')
                                    self.catch_lowest[k][curr_time] = today_lowest  # self.logger.info(f"lowest_point!!!: {self.lowest_price[k]}")
                                    # self.logger.debug(f"{k} catch_lowest:{self.catch_lowest[k]}")
                                else:
                                    self.catch_lowest[k][curr_time] = v

                                # self.logger.debug(f"{k} catch_lowest:{self.catch_lowest[k]}")
                            except Exception as e:
                                self.logger.error(e)
                            # 判断是否跳出交易
                            # ---------------------------------------------------------------------------------------
                            # 判断当前价格是否有效
                            if curr_price == 0:
                                continue

                            try:
                                # 计算当前ma5
                                self.code_ma[k]['curr_ma5'] = (self.code_ma[k]['sum_ma4'] + curr_price) / 5
                                self.code_ma[k]['curr_ma6'] = (self.code_ma[k]['sum_ma5'] + curr_price) / 6
                                self.code_ma[k]['curr_ma7'] = (self.code_ma[k]['sum_ma6'] + curr_price) / 7
                                self.code_ma[k]['curr_ma8'] = (self.code_ma[k]['sum_ma7'] + curr_price) / 8

                                # self.logger.debug(f"{k} self.code_ma[k]:{self.code_ma[k]}")
                            except Exception as e:
                                self.logger.error(e)

                            # 判断是否出现顶背离
                            top_beili_cond1 = (self.code_ma[k]['yes2_close'] >= self.code_ma[k]['yes1_close'] or
                                     self.code_ma[k]['yes2_lowest'] >= self.code_ma[k]['yes1_lowest'] or
                                     self.code_ma[k]['yes2_highest'] >= self.code_ma[k]['yes1_highest'] or
                                     self.code_ma[k]['yes1_lowest'] > curr_price)
                            top_beili_cond2 = (self.code_ma[k]['yes1_ma8'] > curr_price or
                                               self.code_ma[k]['yes1_ma7'] > curr_price or
                                               self.code_ma[k]['yes1_ma6'] > curr_price or
                                                self.code_ma[k]['yes1_ma5'] > curr_price or
                                                self.code_ma[k]['yes1_ma4'] > curr_price)

                            top_beili_cond3 = (self.code_ma[k]['yes1_ma7'] > self.code_ma[k]['yes2_ma7'] or
                                     self.code_ma[k]['yes1_ma6'] > self.code_ma[k]['yes2_ma6'] or
                                     self.code_ma[k]['yes1_ma8'] > self.code_ma[k]['yes2_ma8'] or
                                     self.code_ma[k]['yes1_ma6'] < self.code_ma[k]['curr_ma6'] or
                                     self.code_ma[k]['yes1_ma7'] < self.code_ma[k]['curr_ma7'] or
                                     self.code_ma[k]['yes1_ma8'] < self.code_ma[k]['curr_ma8'])

                            # 是否是假底背离，继续下跌
                            top_beili_cond4 = ((self.code_ma[k]['yes1_ma7'] < self.code_ma[k]['yes2_ma7'] and
                                     self.code_ma[k]['yes1_ma6'] < self.code_ma[k]['yes2_ma6'] and
                                     self.code_ma[k]['yes1_ma8'] < self.code_ma[k]['yes2_ma8']) or
                                    (self.code_ma[k]['yes1_ma6'] > self.code_ma[k]['curr_ma6'] and
                                     self.code_ma[k]['yes1_ma7'] > self.code_ma[k]['curr_ma7'] and
                                     self.code_ma[k]['yes1_ma8'] > self.code_ma[k]['curr_ma8']))

                            if top_beili_cond1 and top_beili_cond2 and (top_beili_cond3 or top_beili_cond4):
                                self.isAppear_top[k] = True


                            # 如果最近一条记录是top，那么跳过买动作
                            if k in self.isAppear_top and self.isAppear_top[k]:
                                continue

                            # 如果你是底部，但是现在价格低于了这个底部，那就不能买，应该全卖出
                            if self.code_ma[k]['yes1_lowest'] > curr_price:
                                continue

                            # 设置购买金额
                            # ---------------------------------------------------------------------------------------
                            # 设定所有股票总仓位
                            try:
                                # 若果仓位超标，退出交易
                                all_buy = self.trend_rec.find({'isSold': 0})
                                today_all_buy = self.hasBuy.find({'buy_date': self.today})
                                all_buy_money = 0
                                for a in all_buy:
                                    all_buy_money += a['left_num'] * a['cost']
                                for t in today_all_buy:
                                    all_buy_money += t['money']

                                if all_buy_money >= self.trends_top_money:
                                    continue

                                # self.logger.debug(f"{k} all_buy_money:{all_buy_money}, self.per_top_money:{self.per_top_money}")

                            except Exception as e:
                                self.logger.error(e)



                            if self.code_ma[k]['yes1_macd'] >= 0.011 and self.code_ma[k]['yes2_lowest'] < self.code_ma[k]['yes1_lowest'] and self.code_ma[k]['yes2_highest'] < self.code_ma[k]['yes1_highest']:
                                self.money1 = 0
                                self.money2 = self.per_top_money
                                self.money3 = self.per_top_money * 2
                                self.money4 = self.per_top_money * 2
                                self.money5 = 0
                                bt1_nums = self.hasBuy.count_documents({'bt': 1, 'buy_date': self.today})
                                bt2_nums = self.hasBuy.count_documents({'bt': 2, 'buy_date': self.today})
                                bt3_nums = self.hasBuy.count_documents({'bt': 3, 'buy_date': self.today})
                                bt4_nums = self.hasBuy.count_documents({'bt': 4, 'buy_date': self.today})
                                bt5_nums = self.hasBuy.count_documents({'bt': 5, 'buy_date': self.today})
                                bt2_lst = self.hasBuy.find({'bt': 2, 'buy_date': self.today})
                                bt3_lst = self.hasBuy.find({'bt': 3, 'buy_date': self.today})
                                bt4_lst = self.hasBuy.find({'bt': 4, 'buy_date': self.today})
                                bt2_codes = []
                                bt3_codes = []
                                bt4_codes = []
                                for b in bt2_lst:
                                    bt2_codes.append(b['code'])
                                for b in bt3_lst:
                                    bt3_codes.append(b['code'])
                                for c in bt4_lst:
                                    bt4_codes.append(c['code'])
                                # print('bt3_codes', bt3_codes)
                                # print('bt4_codes', bt4_codes)
                                if bt2_nums > 8 and (k not in bt2_codes):
                                    continue
                                if bt3_nums > 4 and (k not in bt3_codes):
                                    continue
                                if bt4_nums > 2 and (k not in bt4_codes):
                                    continue


                                if bt2_nums <= 2:
                                    self.money1 = 0
                                    self.money2 = self.per_top_money * 2
                                    self.money3 = self.per_top_money * 2
                                    self.money4 = self.per_top_money * 3
                                    self.money5 = 0
                                elif bt2_nums <= 5:
                                    self.money1 = 0
                                    self.money2 = self.per_top_money
                                    self.money3 = self.per_top_money * 2
                                    self.money4 = self.per_top_money * 3
                                    self.money5 = 0
                                else:
                                    self.money1 = 0
                                    self.money2 = self.per_top_money
                                    self.money3 = self.per_top_money
                                    self.money4 = self.per_top_money * 2
                                    self.money5 = 0
                            else:
                                self.money1 = 0
                                self.money2 = 0
                                self.money3 = 0
                                self.money4 = 0
                                self.money5 = 0
                                continue

                            # 买入监控
                            # ---------------------------------------------------------------------------------------
                            buy_cond1 = (len(self.catch_lowest[k]) > 1)
                            buy_cond2 = (self.catch_lowest[k].iloc[0] == today_lowest)
                            buy_cond3 = (self.catch_lowest[k].max() == self.catch_lowest[k].iloc[-1])
                            # buy_cond4 = (self.catch_lowest[k].iloc[-1] - today_lowest)/today_lowest >= 0.03
                            buy_cond4 = (self.catch_lowest[k].iloc[-1] - today_lowest) >= 0.03
                            # 如果当前记录长度大于1，且最新进场价格大于第一个价格(最低价格)，那么买入？
                            if buy_cond1 and buy_cond2 and buy_cond3 and buy_cond4 and ((curr_time.hour == 9 and curr_time.minute >= 31) or curr_time.hour >= 10):

                                # log_info = str(k) + ' Enter jk_buy 1 Level, ' + '差值: ' + str(
                                #     (self.catch_lowest[k].iloc[-1] - today_lowest) / today_lowest)
                                # self.logger.info(log_info)
                                self.logger.debug(f"{k} in jk_buy: self.catch_lowest[k].iloc[-1] - today_lowest = {self.catch_lowest[k].iloc[-1] - today_lowest}")
                                # 根据标的价位设定入场目标
                                act = 'buy'

                                # 查询时间
                                hasBuy = self.hasBuy.count_documents({'code': k, 'buy_date': self.today})
                                ndict = {}
                                ndict['code'] = k
                                ndict['price'] = curr_price
                                luocha = 0.0046

                                if hasBuy == 0 and act == 'buy':
                                    try:
                                        money = 0
                                        buyMoney = 0
                                        ndict['bt'] = 1
                                        # 计算成本单价
                                        # cost = (buyMoney + 15) / (round(money / ndict['price'] / 100) * 100)
                                        # num = (round(money / ndict['price'] / 100) * 100)
                                        cost = 0
                                        num = 0
                                        self.hasBuy.insert_one({'code': k, 'price': curr_price, 'time': str(curr_time), 'buy_date': self.today, 'bt': 1, 'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0, 'yingkui': 0})

                                        # self.autoBuy(ndict, money, 'sale1')
                                        buy_price = ndict['price'] + 0.01

                                        if money != 0:
                                            with self.trade_lock:
                                                res = self.trader.auto_buy_chrome(k, buy_price, num)

                                            self.logger.info(str(k) + ' bt1买入, 单价:' + str(buy_price) + ' 数量:' + str(num) + ' 返回结果：' + str(res))

                                        self.catch_lowest[k] = pd.Series(dtype='float64')

                                    except Exception as e:
                                        self.logger.error(f"error: {r['code']}, {e}")

                                elif hasBuy == 1 and act == 'buy':

                                    # 判断间隔时间
                                    try:
                                        res = self.hasBuy.find_one({'code': ndict['code'], 'buy_date': self.today, 'bt': 1})
                                        t1 = datetime.datetime.strptime(res['time'][0:19], '%Y-%m-%d %H:%M:%S')

                                        if (curr_time - t1).total_seconds() > 480 and (res['price'] - curr_price)/res['price'] >= luocha:

                                            money = self.money2
                                            if money + all_buy_money > self.trends_top_money and all_buy_money < self.trends_top_money:
                                                money = self.trends_top_money - all_buy_money

                                            # 计算成本单价
                                            num = (round(money / ndict['price'] / 100) * 100)
                                            if num == 0 and money != 0:
                                                num = 100

                                            buyMoney = num * curr_price
                                            cost = (buyMoney + 15) / num

                                            ndict['bt'] = 2
                                            self.hasBuy.insert_one({'code': k, 'price': curr_price, 'time': str(curr_time), 'buy_date': self.today, 'bt': ndict['bt'], 'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0, 'yingkui': 0})

                                            # self.autoBuy(ndict, money, 'sale1')
                                            buy_price = ndict['price'] + 0.01
                                            with self.trade_lock:
                                                # res = self.trader.auto_buy_chrome(k, buy_price, num)
                                                res = self.trader.auto_buy_session(k, buy_price, num)
                                                self.logger.info(str(k) + ' bt2买入, 单价:' + str(buy_price) + ' 数量:' + str(num) + ' 返回结果：' + str(res))

                                            self.catch_lowest[k] = pd.Series(dtype='float64')
                                    except Exception as e:
                                        self.logger.error(f"error: {r['code']}, {e}")
                                elif hasBuy == 2 and act == 'buy':

                                    # 判断间隔时间
                                    try:
                                        res = self.hasBuy.find_one({'code': ndict['code'], 'buy_date': self.today, 'bt': 2})
                                        t1 = datetime.datetime.strptime(res['time'][0:19], '%Y-%m-%d %H:%M:%S')

                                        if (curr_time - t1).total_seconds() > 480 and (res['price'] - curr_price)/res['price'] >= luocha:
                                            # money = self.money3
                                            # if res['money'] == 0:
                                            #     money = res['money']
                                            #     buyMoney = 0
                                            #     # 计算成本单价
                                            #     cost = 0
                                            #     num = 0
                                            # else:
                                            money = self.money3

                                            if money + all_buy_money > self.trends_top_money and all_buy_money < self.trends_top_money:
                                                money = self.trends_top_money - all_buy_money

                                            # 计算成本单价
                                            num = (round(money / ndict['price'] / 100) * 100)
                                            if num == 0 and money != 0:
                                                num = 100

                                            buyMoney = num * curr_price
                                            cost = (buyMoney + 15) / num

                                            ndict['bt'] = 3
                                            self.hasBuy.insert_one({'code': k, 'price': curr_price, 'time': str(curr_time), 'buy_date': self.today, 'bt': ndict['bt'], 'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0, 'yingkui': 0})

                                            # self.autoBuy(ndict, money, 'sale1')
                                            buy_price = ndict['price'] + 0.01
                                            with self.trade_lock:
                                                # res = self.trader.auto_buy_chrome(k, buy_price, num)
                                                res = self.trader.auto_buy_session(k, buy_price, num)
                                                self.logger.info(str(k) + ' bt3买入, 单价:' + str(buy_price) + ' 数量:' + str(num) + ' 返回结果：' + str(res))

                                            self.catch_lowest[k] = pd.Series(dtype='float64')
                                    except Exception as e:
                                        self.logger.error(f"error: {r['code']}, {e}")

                                elif hasBuy == 3 and act == 'buy':

                                    # 判断间隔时间
                                    try:
                                        res = self.hasBuy.find_one({'code': ndict['code'], 'buy_date': self.today, 'bt': 3})
                                        t1 = datetime.datetime.strptime(res['time'][0:19], '%Y-%m-%d %H:%M:%S')

                                        if (curr_time - t1).total_seconds() > 480 and (res['price'] - curr_price)/res['price'] >= luocha:
                                            # money = self.money3
                                            # if res['money'] == 0:
                                            #     money = res['money']
                                            #     buyMoney = 0
                                            #     # 计算成本单价
                                            #     cost = 0
                                            #     num = 0
                                            # else:
                                            money = self.money4

                                            if money + all_buy_money > self.trends_top_money and all_buy_money < self.trends_top_money:
                                                money = self.trends_top_money - all_buy_money

                                            # 计算成本单价
                                            num = (round(money / ndict['price'] / 100) * 100)
                                            if num == 0 and money != 0:
                                                num = 100

                                            buyMoney = num * curr_price
                                            cost = (buyMoney + 15) / num

                                            ndict['bt'] = 4
                                            self.hasBuy.insert_one({'code': k, 'price': curr_price, 'time': str(curr_time), 'buy_date': self.today, 'bt': ndict['bt'], 'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0, 'yingkui': 0})

                                            # self.autoBuy(ndict, money, 'sale1')
                                            buy_price = ndict['price'] + 0.01
                                            with self.trade_lock:
                                                # res = self.trader.auto_buy_chrome(k, buy_price, num)
                                                res = self.trader.auto_buy_session(k, buy_price, num)
                                                self.logger.info(str(k) + ' bt4买入, 单价:' + str(buy_price) + ' 数量:' + str(num) + ' 返回结果：' + str(res))

                                            self.catch_lowest[k] = pd.Series(dtype='float64')
                                    except Exception as e:
                                        self.logger.error(f"error: {r['code']}, {e}")

                                # elif hasBuy == 4 and act == 'buy':  #  #     # 判断间隔时间  #     try:  #         res = self.hasBuy.find_one(  #             {'code': ndict['code'], 'buy_date': self.today, 'bt': 3})  #         t1 = datetime.datetime.strptime(res['time'][0:19], '%Y-%m-%d %H:%M:%S')  #  #         if (curr_time - t1).total_seconds() > 480 and (res['price'] - curr_price)/res['price'] >= luocha:  #  #             # money = self.money5  #  #             if res['money'] == 0:  #                 money = res['money']  #                 buyMoney = 0  #                 ndict['bt'] = 5  #                 # 计算成本单价  #                 cost = 0  #                 num = 0  #             else:  #                 money = res['money']  #  #                 if money + all_buy_money > self.trends_top_money and all_buy_money < self.trends_top_money:  #                     money = self.trends_top_money - all_buy_money  #  #                 buyMoney = (round(money / ndict['price'] / 100) * 100) * curr_price  #                 ndict['bt'] = 5  #                 # 计算成本单价  #                 cost = (buyMoney + 15) / (round(money / ndict['price'] / 100) * 100)  #                 num = (round(money / ndict['price'] / 100) * 100)  #             self.hasBuy.insert_one(  #                 {'code': k, 'price': curr_price, 'time': str(curr_time),  #                  'buy_date': self.today, 'bt': ndict['bt'],  #                  'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0,  #                  'yingkui': 0})  #  #             buy_price = ndict['price'] + 0.001  #             if self.money5 != 0:  #                 res = self.trader.auto_buy_chrome(k, buy_price, num)  #  #             self.logger.info(  #                 str(k) + ' bt1买入, 单价:' + str(buy_price) + ' 数量:' + str(  #                     num) + ' 返回结果：' + str(res))  #  #             self.catch_lowest[k] = pd.Series(dtype='float64')  #     except Exception as e:  #         self.logger.error(e)
                        except Exception as e:
                            self.logger.error(str(k) + ' error :' + str(e))

            if curr_time.hour >= 15 and curr_time.minute >= 3:
                break
        today_hasBuy = self.hasBuy.find({'buy_date': self.today})
        for thb in today_hasBuy:
            print(thb)
            k = thb['code']
            num = 0
            buyMoney = 0
            hasBuy = self.hasBuy.find({'code': k, 'buy_date': self.today})
            curr_time = datetime.datetime.now()
            bts = 0

            for h in hasBuy:
                num += h['num']
                buyMoney += h['money']
                bts += 1
            if num != 0:
                cost = round(buyMoney / num, 4)
                print({'code': k, 'price': cost, 'time': str(curr_time), 'buy_date': self.today, 'bt': 1, 'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0, 'yingkui': 0, 'highest_price': cost})
                count = self.trend_rec.count_documents({'code': k, 'buy_date': self.today})

                if count == 0 and num != 0:
                    self.trend_rec.insert_one({'code': k, 'price': cost, 'time': str(curr_time), 'buy_date': self.today, 'bt': 1, 'money': buyMoney, 'isSold': 0, 'cost': cost, 'num': num, 'pct_bt': 0, 'yingkui': 0, 'yingkui1': 0, 'yingkui2': 0, 'yingkui3': 0, 'left_num': num, 'bts': bts, 'st': 0, 'highest_price': cost})  # 获取每支个股最近插入的背离数据

    def jk_sale(self):
        while True:
            curr_time = datetime.datetime.now()
            ser = self.ser
            lastreq = self.lastreq
            # print(self.ser)
            # print(self.lastreq)

            if len(ser) == 0 or len(lastreq) == 0:
                continue

            #     if (curr_time.hour == 11 and curr_time.minute > 30) or curr_time.hour == 12:
            #         continue
            #     elif curr_time.hour >= 15 and curr_time.minute > 2:
            #         break
            #     elif (curr_time.hour == 9 and curr_time.minute >= 30) or curr_time.hour >= 10:
            #         self.logger.warning(f'In jk_sale ser or lastreq is empty:{curr_time}')
            #         time.sleep(1)
            #         continue

            log_msg = ' Sale: ' + ' curr_time:' + str(curr_time)

            if curr_time.hour >= 9 and curr_time.hour <= 15:
                if (curr_time.hour == 11 and curr_time.minute > 30) or curr_time.hour == 12:
                    continue
                elif curr_time.hour >= 15 and curr_time.minute > 1:
                    break
                elif (curr_time.hour == 9 and curr_time.minute >= 30) or curr_time.hour >= 10:

                    # if curr_time.hour >= 9 and curr_time.hour <= 15:
                    #     if (curr_time.hour == 9 and curr_time.minute >= 30) or curr_time.hour >= 10:
                    try:
                        # 获取市场行情，进行交易评级quotation
                        # pct_sh, pct_sz = self.dp()
                        # qttA = 0.65
                        # qttB = 0.5
                        # qttC = 0.35
                        # qttD = 0.2

                        # 查询已买,且有仓位可以卖
                        res = self.trend_rec.find({'isSold': 0})

                        # 因为一个code,未卖出单子可能很多，如果其中一个满足条件卖出就清空self.catch_highest是不合理的，所以需要等这个code的遍历完了，只要有卖出就清空
                        # clean_flag = False
                        for r in res:
                            self.clean_flag[r['code']] = False

                        res = self.trend_rec.find({'isSold': 0})
                        for r in res:
                            try:
                                # self.logger.info(f"In jk_sale1:{r}")
                                k = r['code']
                                if r['money'] == 0:
                                    continue
                                # self.logger.info(f"In jk_sale2:{r}")
                                try:

                                    # 没有被卖，那么获取当前分时价格，然后和bt价格对比
                                    today_highest = lastreq[k]['today_highest']
                                    curr_price = lastreq[k]['curr_price']

                                    curr_time_temp = str(curr_time)
                                    if self.highest_price[k] < today_highest:
                                        self.highest_price[k] = today_highest
                                        self.catch_highest[k] = pd.Series(dtype='float64')
                                        self.catch_highest[k][curr_time_temp] = today_highest
                                        # self.logger.debug(f"self.highest_price[k]:{self.highest_price[k]}")
                                    else:
                                        self.catch_highest[k][curr_time_temp] = ser[k]
                                except Exception as e:
                                    raise e

                                # 更新当前盈利情况
                                # new_yingkui = r['num'] * (curr_price - r['cost'])
                                # pct_bt = round((curr_price - r['cost']) / r['cost'], 4)
                                # self.trend_rec.update_one({'code': k, 'time': r['time']},
                                #                           {'$set': {'pct_bt': pct_bt, 'yingkui': new_yingkui}})

                                # new_yingkui = r['left_num'] * (curr_price - r['cost']) + r['yingkui1'] + r['yingkui2'] + r['yingkui3']
                                # pct_bt = round((curr_price - r['cost']) / r['cost'], 4)
                                # if not new_yingkui:
                                #     new_yingkui = 0
                                # if not pct_bt:
                                #     pct_bt = 0
                                # self.trend_rec.update_one({'code': k, 'time': r['time'], '_id': r['_id']},
                                #                           {'$set': {'pct_bt': pct_bt, 'yingkui': new_yingkui}})

                                # 更新当前距离成本价之后的最高价格
                                if curr_price > r['highest_price']:
                                    self.trend_rec.update_one({'code': k, '_id': r['_id']}, {'$set': {'highest_price': curr_price, 'highest_time': str(curr_time)}})

                                    r['highest_price'] = curr_price

                                if curr_price == 0:
                                    continue

                                dict = {}
                                dict['code'] = k
                                # self.logger.debug(f"In jk_sale3:{r}")

                                # ----------------------------------------------------------
                                # 卖出逻辑：如果价格回撤0.003个点，与昨日买入或者今日买入价格对比。
                                # 不管现价是否低于昨日最低买入价格，那么都要记录当前价格，因为当在今日买入时，需要比较现价与当日买入价格，但是如果现价低于了当日买入价格，那就没有再记录的必要。
                                # if ser[k] == today_highest:
                                #     self.catch_highest[k] = pd.Series(dtype='float64')

                                # 把分时时时价格存入
                                # curr_time_temp = str(curr_time)
                                # self.catch_highest[k][curr_time_temp] = ser[k]

                                # 根据市场情绪调整止盈位置
                                # if pct_sh >= qttA or pct_sz >= qttA:
                                #     zhiying = 0.012
                                # elif pct_sh >= qttB or pct_sz >= qttB:
                                #     zhiying = 0.008
                                # elif pct_sh >= qttC or pct_sz >= qttC:
                                #     zhiying = 0.004
                                # elif pct_sh >= qttD or pct_sz >= qttD:
                                #     zhiying = 0.001
                                # else:
                                #     zhiying = 0.0005

                                # 获取今日是否有买入
                                # for today_buy in self.trend_rec.find({'code':k,'buy_date':self.today}):

                                # latest_rec = self.beili.find({'code': k}).sort('_id', -1).limit(1)
                                # latest_rec = [x for x in latest_rec]
                                # if latest_rec and latest_rec[0]['type'] == 'bottom':
                                #     if self.code_ma[k]['yes1_macd'] <= 0.011:
                                #         zhiying_del = int(latest_rec[0]['trade_days']) * 0.004
                                #     elif self.code_ma[k]['yes1_macd'] > 0.011:
                                #         zhiying_del = int(latest_rec[0]['trade_days']) * 0.002
                                # else:
                                #     zhiying_del = 0

                                # 获取仓位情况,仓位控制，单只个股超过指定仓位，那么什么都不要做了，睡觉吧！！！
                                # cangWei = 0
                                # todayCang = self.trend_rec.find({'code': k, 'isSold': 0})
                                # for t in todayCang:
                                #     cangWei += t['money']
                                #
                                # sold_type = ''
                                # if cangWei > self.top_cangwei4:
                                #     zhiying = 0.01 - zhiying_del
                                #     sold_type = 'cangWei > self.top_cangwei4'
                                # elif cangWei > self.top_cangwei3:
                                #     zhiying = 0.014 - zhiying_del
                                #     sold_type = 'cangWei > self.top_cangwei3'
                                # elif cangWei > self.top_cangwei2:
                                #     zhiying = 0.018 - zhiying_del
                                #     sold_type = 'cangWei > self.top_cangwei2'
                                # elif cangWei > self.top_cangwei1:
                                #     zhiying = 0.022 - zhiying_del
                                #     sold_type = 'cangWei > self.top_cangwei1'
                                # else:
                                #     zhiying = 0.026 - zhiying_del
                                #     sold_type = 'yingli0.068'
                                #
                                # if zhiying < 0.004:
                                #     zhiying = 0.004

                                # 如果出现顶背离现象，且还不是特别严重，降低止盈位置

                                # cond1 = (self.code_ma[k]['yes2_close'] >= self.code_ma[k]['yes1_close'] or
                                #          self.code_ma[k]['yes2_lowest'] >= self.code_ma[k]['yes1_lowest'] or
                                #          self.code_ma[k]['yes2_highest'] >= self.code_ma[k]['yes1_highest'])
                                #
                                # cond2 = (self.code_ma[k]['yes1_ma4'] > curr_price or
                                #          self.code_ma[k]['yes1_ma5'] > curr_price or
                                #          self.code_ma[k]['yes1_ma6'] > curr_price or
                                #          self.code_ma[k]['yes1_ma7'] > curr_price)
                                #
                                # cond3 = (self.code_ma[k]['yes1_ma7'] > self.code_ma[k]['yes2_ma7'] or
                                #          self.code_ma[k]['yes1_ma6'] > self.code_ma[k]['yes2_ma6'] or
                                #          self.code_ma[k]['yes1_ma8'] > self.code_ma[k]['yes2_ma8'])

                                # if cond1 and cond2 and cond3:
                                #
                                #     if cangWei > self.top_cangwei4:
                                #         zhiying = -0.01
                                #         sold_type = 'cangWei > self.top_cangwei4, beili'
                                #     elif cangWei > self.top_cangwei3:
                                #         zhiying = 0
                                #         sold_type = 'cangWei > self.top_cangwei3, beili'
                                #     elif cangWei > self.top_cangwei2:
                                #         zhiying = 0.004
                                #         sold_type = 'cangWei > self.top_cangwei2, beili'
                                #     elif cangWei > self.top_cangwei1:
                                #         zhiying = 0.009
                                #         sold_type = 'cangWei > self.top_cangwei1, beili'
                                #     else:
                                #         zhiying = 0.012
                                #         sold_type = '轻微 top beili'

                                # 当大于昨日成本价之后，才开始监控回落
                                zhiying = 0.03
                                sold_type = 'zhiying0.03'
                                sale_cond1 = ((curr_price - r['cost']) / r['cost'] >= zhiying)
                                # sale_cond2 = (len(self.catch_highest[k]) > 1)
                                # sale_cond3 = (today_highest >= self.catch_highest[k].iloc[0])
                                # sale_cond4 = (self.catch_highest[k].iloc[0] >= (today_highest - 0.0015))
                                # sale_cond5 = (self.catch_highest[k].min() == self.catch_highest[k].iloc[-1])

                                # sale_cond1 = True
                                # sale_cond2 = True
                                # sale_cond3 = True
                                # sale_cond4 = True
                                # sale_cond5 = True

                                # 如果昨日仓位大于4次购买，约大于6000 , 那么在当日最高点卖出，不再积累仓位
                                # try:
                                #     yes_buy = self.trend_rec.find_one(
                                #         {'code': k, 'isSold': 0, 'buy_date': self.yestoday})
                                #     # self.logger.debug(f"{yes_buy}")
                                #
                                #     if 'money' in yes_buy:
                                #         yes_cang = yes_buy['money']
                                #         if yes_cang >= self.money2*4:
                                #             sale_cond1 = True
                                #             self.logger.debug(f"sale_cond1:{sale_cond1}")
                                #
                                # except Exception as e:
                                #     self.logger.error(e)


                                try:
                                    # 计算当前ma5
                                    self.code_ma[k]['curr_ma5'] = (self.code_ma[k]['sum_ma4'] + curr_price) / 5
                                    self.code_ma[k]['curr_ma6'] = (self.code_ma[k]['sum_ma5'] + curr_price) / 6
                                    self.code_ma[k]['curr_ma7'] = (self.code_ma[k]['sum_ma6'] + curr_price) / 7
                                    self.code_ma[k]['curr_ma8'] = (self.code_ma[k]['sum_ma7'] + curr_price) / 8

                                    # self.logger.debug(f"{k} self.code_ma[k]:{self.code_ma[k]}")
                                except Exception as e:
                                    self.logger.error(e)

                                # 判断是否出现顶背离
                                is_top_beili = self.code_ma[k]['beili'] == 'top' and self.isAppear_top

                                if (self.code_ma[k]['yes1_highest'] < self.code_ma[k]['yes2_highest'] and self.code_ma[k]['yes1_lowest'] < self.code_ma[k]['yes2_lowest']) or (self.code_ma[k]['yes1_macd'] <= 0.01 and (not (self.code_ma[k]['yes1_highest'] > self.code_ma[k]['yes2_highest'] and self.code_ma[k]['yes1_lowest'] > self.code_ma[k]['yes2_lowest']))):
                                    sale_cond1 = True
                                    sold_type = "xiadie_trend"
                                if is_top_beili:
                                    sale_cond1 = True
                                    sold_type = "top_beili"

                                if curr_time.minute % 39 == 0 and curr_time.second % 60 == 0:
                                    print('jk_sale is alive:', curr_time.time(), len(self.ser))
                                # self.logger.debug(f"In jk_sale4:{r}")

                                # if sale_cond1 and sale_cond2 and sale_cond3 and sale_cond4 and sale_cond5:
                                if sale_cond1:

                                    # self.logger.info(log_msg + '进入if')
                                    # print('jk_sale:',self.catch_highest[k])

                                    # 判断回落点,设置止盈
                                    act = ''
                                    # 判断回落点数是否大于0.003
                                    # if self.catch_highest[k].max() - self.catch_highest[k][-1] >= 0.003:

                                    if (sold_type == "xiadie_trend" or sold_type == "top_beili") and (curr_time.hour == 14 and curr_time.minute >= 53):
                                        if r['st'] != 0:
                                            dict['num'] = r['left_num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            curr_yingkui = dict['num'] * (curr_price - r['cost'])
                                            yingkui = curr_yingkui + r['yingkui']
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': 1, 'left_num': 0,
                                                 'st':r['st']+1,
                                                 f"soldTime{r['st']+1}": str(curr_time),
                                                 f"soldPrice{r['st']+1}": curr_price,
                                                 f"sold_type{r['st']+1}": sold_type,
                                                 f"yingkui{r['st']+1}": curr_yingkui,
                                                 'yingkui': yingkui}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            # 查询剩余仓位，全部清仓
                                            # res_dct = self.trader.get_nums()
                                            # dict['num'] = res_dct[k[2:]]
                                            uNum = self.trend_reality.find_one({'code': k})
                                            try:
                                                with self.trade_lock:
                                                    if uNum and int(uNum['uNum']) == int(dict['num']):
                                                        res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    else:
                                                        res = self.trader.auto_sale_chrome(k, sale_price, 'all')
                                                    self.logger.info(f"sold_point1: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error2: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # # send_notice('Sold_Error2', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                        else:
                                            dict['num'] = r['left_num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            yingkui = dict['num'] * (curr_price - r['cost'])
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': 1, 'left_num': 0, 'st':1, 'soldTime1': str(curr_time),
                                                         'soldPrice1': curr_price, 'sold_type1': sold_type,
                                                 'yingkui1': yingkui, 'yingkui': yingkui}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            # 查询剩余仓位，全部清仓
                                            # res_dct = self.trader.get_nums()
                                            # dict['num'] = res_dct[k[2:]]
                                            uNum = self.trend_reality.find_one({'code': k})
                                            try:
                                                with self.trade_lock:
                                                    if uNum and int(uNum['uNum']) == int(dict['num']):
                                                        res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    else:
                                                        res = self.trader.auto_sale_chrome(k, sale_price, 'all')
                                                    self.logger.info(f"sold_point2: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error4: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # # send_notice('Sold_Error4', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                    elif (sold_type == "xiadie_trend" or sold_type == "top_beili") and ((self.catch_highest[k].max() - self.catch_highest[k][-1])/self.catch_highest[k].max() >= 0.003):
                                        if r['st'] == 0:
                                            if r['left_num'] < 300:
                                                dict['num'] = r['left_num']
                                                isSold = 1
                                                # # 查询剩余仓位，全部清仓
                                                # res_dct = self.trader.get_nums()
                                                # dict['num'] = res_dct[k[2:]]
                                            else:
                                                dict['num'] = int(r['left_num'] / 300) * 200
                                                isSold = 0
                                            left_num = r['left_num'] - dict['num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            yingkui1 = dict['num'] * (curr_price - r['cost'])
                                            yingkui = yingkui1
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': isSold, 'st': 1, 'left_num': left_num, 'left_num1': left_num,
                                                         'soldNum1': dict['num'], 'soldTime1': str(curr_time),
                                                         'soldPrice1': curr_price,
                                                         'yingkui': yingkui, 'yingkui1': yingkui1, 'sold_type1': sold_type}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            try:
                                                dict['num'] = 'all' if isSold == 1 else dict['num']
                                                with self.trade_lock:
                                                    res = self.trader.auto_sale_chrome(k, sale_price, dict['num'])
                                                    # res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    self.logger.info(f"sold_point5: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error9: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # # send_notice('Sold_Error9', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                        elif r['st'] == 1 and (curr_price - r['soldPrice1'])/r['soldPrice1'] >= 0.003:
                                            if r['left_num'] < 300:
                                                dict['num'] = r['left_num']
                                                isSold = 1
                                                # # 查询剩余仓位，全部清仓
                                                # res_dct = self.trader.get_nums()
                                                # dict['num'] = res_dct[k[2:]]
                                            else:
                                                dict['num'] = int(r['left_num'] / 300) * 200
                                                isSold = 0
                                            left_num = r['left_num'] - dict['num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            yingkui2 = dict['num'] * (curr_price - r['cost'])
                                            yingkui = r['yingkui1'] + yingkui2
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': isSold, 'st': 2, 'left_num': left_num, 'left_num2': left_num,
                                                         'soldNum2': dict['num'], 'soldTime2': str(curr_time),
                                                         'soldPrice2': curr_price,
                                                         'yingkui': yingkui, 'yingkui2': yingkui2, 'sold_type2': sold_type}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            try:
                                                dict['num'] = 'all' if isSold == 1 else dict['num']
                                                with self.trade_lock:
                                                    res = self.trader.auto_sale_chrome(k, sale_price, dict['num'])
                                                    # res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    self.logger.info(f"sold_point6: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error10: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # # send_notice('Sold_Error10', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                        elif r['st'] == 2 and (curr_price - r['soldPrice2'])/r['soldPrice2'] >= 0.003:
                                            dict['num'] = r['left_num']
                                            left_num = r['left_num'] - dict['num']
                                            condition = {'code': r['code'], '_id': r['_id']}
                                            yingkui3 = dict['num'] * (curr_price - r['cost'])
                                            yingkui = r['yingkui1'] + r['yingkui2'] + yingkui3
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': 1, 'st': 3, 'left_num': left_num, 'left_num3': left_num,
                                                         'soldNum3': dict['num'], 'soldTime3': str(curr_time),
                                                         'soldPrice3': curr_price,
                                                         'yingkui': yingkui, 'yingkui3': yingkui3, 'sold_type3': sold_type}})
                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            # try:
                                            #     # 查询剩余仓位，全部清仓
                                            #     res_dct = self.trader.get_nums()
                                            #     dict['num'] = res_dct[k[2:]]
                                            # except Exception as e:
                                            #     self.logger.error(f"Sold_Error11: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                            #     # # send_notice('Sold_Error11', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                            uNum = self.trend_reality.find_one({'code': k})
                                            try:
                                                with self.trade_lock:
                                                    if uNum and int(uNum['uNum']) == int(dict['num']):
                                                        res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    else:
                                                        res = self.trader.auto_sale_chrome(k, sale_price, 'all')
                                                    self.logger.info(f"sold_point7: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error12: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # # send_notice('Sold_Error12', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                    elif (r['highest_price'] - curr_price) / r['highest_price'] > 0.008 and curr_price > r['cost']:
                                        sold_type = '止盈0.008'
                                        if r['st'] != 0:
                                            dict['num'] = r['left_num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            curr_yingkui = dict['num'] * (curr_price - r['cost'])
                                            yingkui = curr_yingkui + r['yingkui']

                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': 1, 'left_num': 0,
                                                         'st': r['st']+1,
                                                         f"soldTime{r['st']+1}": str(curr_time),
                                                         f"soldPrice{r['st']+1}": curr_price,
                                                         f"sold_type{r['st']+1}": sold_type,
                                                         f"yingkui{r['st']+1}": curr_yingkui,
                                                         'yingkui': yingkui}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            # 查询剩余仓位，全部清仓
                                            # res_dct = self.trader.get_nums()
                                            # dict['num'] = res_dct[k[2:]]
                                            uNum = self.trend_reality.find_one({'code': k})
                                            try:
                                                with self.trade_lock:
                                                    if uNum and int(uNum['uNum']) == int(dict['num']):
                                                        res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    else:
                                                        res = self.trader.auto_sale_chrome(k, sale_price, 'all')
                                                    self.logger.info(f"sold_point3: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error6: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # send_notice('Sold_Error6', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                        else:
                                            dict['num'] = r['left_num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            yingkui = dict['num'] * (curr_price - r['cost'])
                                            self.trade_rec.update_one(condition, {
                                                '$set': {'isSold': 1, 'left_num': 0, 'st':1, 'soldTime1': str(curr_time),
                                                         'soldPrice1': curr_price, 'sold_type1': sold_type,
                                                         'yingkui1': yingkui, 'yingkui': yingkui}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            # 查询剩余仓位，全部清仓
                                            # res_dct = self.trader.get_nums()
                                            # dict['num'] = res_dct[k[2:]]
                                            uNum = self.trend_reality.find_one({'code': k})
                                            try:
                                                with self.trade_lock:
                                                    if uNum and int(uNum['uNum']) == int(dict['num']):
                                                        res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    else:
                                                        res = self.trader.auto_sale_chrome(k, sale_price, 'all')
                                                    self.logger.info(f"sold_point4: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error8: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # send_notice('Sold_Error8', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                    elif (r['highest_price'] - curr_price) / r['highest_price'] > 0.004 and curr_price > r['cost']:
                                        sold_type = '止盈0.004'
                                        if r['st'] == 0:
                                            if r['left_num'] < 300:
                                                dict['num'] = r['left_num']
                                                isSold = 1
                                                # 查询剩余仓位，全部清仓
                                                # res_dct = self.trader.get_nums()
                                                # dict['num'] = res_dct[k[2:]]
                                            else:
                                                dict['num'] = int(r['left_num'] / 300) * 200
                                                isSold = 0
                                            left_num = r['left_num'] - dict['num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            yingkui1 = dict['num'] * (curr_price - r['cost'])
                                            yingkui = yingkui1
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': isSold, 'st': 1, 'left_num': left_num, 'left_num1': left_num,
                                                         'soldNum1': dict['num'], 'soldTime1': str(curr_time),
                                                         'soldPrice1': curr_price,
                                                         'yingkui': yingkui, 'yingkui1': yingkui1, 'sold_type1': sold_type}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            try:
                                                dict['num'] = 'all' if isSold == 1 else dict['num']
                                                with self.trade_lock:
                                                    # res = self.trader.auto_sale_chrome(k, sale_price, dict['num'])
                                                    res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    self.logger.info(f"sold_point5: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error9: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # send_notice('Sold_Error9', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                        elif r['st'] == 1 and (curr_price - r['soldPrice1'])/r['soldPrice1'] >= 0.003:
                                            if r['left_num'] < 300:
                                                dict['num'] = r['left_num']
                                                isSold = 1
                                            else:
                                                dict['num'] = int(r['left_num'] / 300) * 200
                                                isSold = 0
                                            left_num = r['left_num'] - dict['num']
                                            condition = {'code': k, 'time': r['time'], '_id': r['_id']}
                                            yingkui2 = dict['num'] * (curr_price - r['cost'])
                                            yingkui = r['yingkui1'] + yingkui2
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': isSold, 'st': 2, 'left_num': left_num, 'left_num2': left_num,
                                                         'soldNum2': dict['num'], 'soldTime2': str(curr_time),
                                                         'soldPrice2': curr_price,
                                                         'yingkui': yingkui, 'yingkui2': yingkui2, 'sold_type2': sold_type}})

                                            # self.autoSale(dict, 1)
                                            sale_price = curr_price - 0.03
                                            try:
                                                dict['num'] = 'all' if isSold == 1 else dict['num']
                                                with self.trade_lock:
                                                    res = self.trader.auto_sale_chrome(k, sale_price, dict['num'])
                                                    self.logger.info(f"sold_point6: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error10: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # send_notice('Sold_Error10', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                        elif r['st'] == 2 and (curr_price - r['soldPrice2'])/r['soldPrice2'] >= 0.003:
                                            dict['num'] = r['left_num']
                                            left_num = r['left_num'] - dict['num']
                                            condition = {'code': r['code'], '_id': r['_id']}
                                            yingkui3 = dict['num'] * (curr_price - r['cost'])
                                            yingkui = r['yingkui1'] + r['yingkui2'] + yingkui3
                                            self.trend_rec.update_one(condition, {
                                                '$set': {'isSold': 1, 'st': 3, 'left_num': left_num, 'left_num3': left_num,
                                                         'soldNum3': dict['num'], 'soldTime3': str(curr_time),
                                                         'soldPrice3': curr_price,
                                                         'yingkui': yingkui, 'yingkui3': yingkui3, 'sold_type3': sold_type}})
                                            sale_price = curr_price - 0.03

                                            uNum = self.trend_reality.find_one({'code': k})
                                            try:
                                                with self.trade_lock:
                                                    if uNum and int(uNum['uNum']) == int(dict['num']):
                                                        res = self.trader.auto_sale_session(k, sale_price, dict['num'])
                                                    else:
                                                        res = self.trader.auto_sale_chrome(k, sale_price, 'all')
                                                    self.logger.info(f"sold_point7: {k}, curr_price:{curr_price}, num:{dict['num']}, response:{res}")
                                            except Exception as e:
                                                self.logger.error(f"Sold_Error12: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")
                                                # send_notice('Sold_Error12', f"Sold_Error1: {k}, time:{curr_time}, sold_type:{sold_type}, e:{e}")

                                    # 如果有进来过那么，clean_flag 标记为清空
                                    self.clean_flag[k] = True

                                # 顶背离清仓  # 获取最近插入的数据  # latest_rec = self.beili.find({'code': k}).sort('_id', -1).limit(1)  # latest_rec = [x for x in latest_rec]

                                # cond1 = (self.code_ma[k]['yes2_close'] >= self.code_ma[k]['yes1_close'] or  #          self.code_ma[k]['yes2_lowest'] >= self.code_ma[k]['yes1_lowest'] or  #          self.code_ma[k]['yes2_highest'] >= self.code_ma[k]['yes1_highest'])  #  # cond2 = self.code_ma[k]['yes1_ma8'] > curr_price  #  # cond3 = (self.code_ma[k]['yes1_ma7'] > self.code_ma[k]['yes2_ma7'] or  #          self.code_ma[k]['yes1_ma6'] > self.code_ma[k]['yes2_ma6'] or  #          self.code_ma[k]['yes1_ma8'] > self.code_ma[k]['yes2_ma8'])

                                # is_false_bottom = (latest_rec and latest_rec[0]['type'] == 'bottom' and latest_rec[0]['price'] * 0.99 > curr_price)  # is_top_beili = latest_rec and latest_rec[0]['type'] == 'top'  #  # if is_top_beili or is_false_bottom:  #     dict['num'] = r['num']  #     condition = {'code': k, 'time': r['time']}  #     yingkui = dict['num'] * (curr_price - r['cost'])  #     self.trend_rec.update_one(condition, {  #         '$set': {'isSold': 1, 'soldTime': str(curr_time), 'soldPrice': curr_price,  #                  'yingkui': yingkui}})  #  #     # self.autoSale(dict, 1)  #     sale_price = curr_price - 0.03  #     res = self.trader.auto_sale_chrome(k, sale_price, dict['num'])  #     self.logger.info(  #         str(k) + ' 卖出, 单价:' + str(curr_price - 0.01) + ' 数量:' + str(  #             dict['num']) + ' 返回结果：' + str(res))

                                # 如果有进来过那么，clean_flag 标记为清空  # self.clean_flag[k] = True

                            except Exception as e:
                                # raise e
                                self.logger.error(f"error: {r['code']} {e}")

                        # 遍历clean_flag字典，如果有True,那么清空
                        for cf in self.clean_flag:
                            if self.clean_flag[cf]:
                                self.catch_highest[cf] = pd.Series(dtype='float64')

                    except Exception as e:
                        self.logger.error(e)
                        print('--------///错误///---------saleProcess 卖出错误:', e)

            if curr_time.hour >= 15 and curr_time.minute >= 2:
                break

    def calculate_profit_one(self, code):

        # 获取昨日清仓盈利情况,昨日可能买了一笔，可能买了多笔
        hasSale = self.trend_rec.find({'code': code, 'isSold': 1})
        noSale = self.trend_rec.find({'code': code, 'isSold': 0})
        hasSale_yingkui = 0
        noSale_yingkui = 0
        sale_money = 0
        noSale_money = 0
        for y in hasSale:
            hasSale_yingkui += y['yingkui']
            sale_money += y['money']
        for k in noSale:
            noSale_yingkui += k['yingkui']
            noSale_money += k['money']

        # 更新到总表里
        total_yingkui = noSale_yingkui + hasSale_yingkui
        # self.allList.update_one({'code': code}, {'$set': {'yingkui': total_yingkui}})
        self.logger.info('截止' + str(self.today) + ' 日 ' + str(code) + ' 盈亏：' + str(total_yingkui) + ' 未卖出金额：' + str(noSale_money) + ' 已卖出金额：' + str(sale_money))

    def calculate_profit(self):

        # 获取昨日清仓盈利情况,昨日可能买了一笔，可能买了多笔
        hasSale = self.trend_rec.find({'isSold': 1})
        noSale = self.trend_rec.find({'isSold': 0})
        hasSale_yingkui = 0
        noSale_yingkui = 0
        sale_money = 0
        noSale_money = 0
        for y in hasSale:
            hasSale_yingkui += y['yingkui']
            sale_money += y['money']
        for k in noSale:
            noSale_yingkui += k['yingkui']
            noSale_money += k['money']

        # 更新到总表里
        total_yingkui = noSale_yingkui + hasSale_yingkui
        # self.allList.update_one({'code': code}, {'$set': {'yingkui': total_yingkui}})
        self.logger.info('截止' + str(self.today) + ' 总盈亏：' + str(total_yingkui) + ' 未卖出金额：' + str(noSale_money) + ' 已卖出金额：' + str(sale_money))

    def get_reality_cangwei(self):
        "https://jywg.18.cn/Search/Position"

        while True:
            curr_time = datetime.datetime.now()
            if curr_time.minute % 25 == 0 and curr_time.second % 59 == 0:
                print("get_reality_cangwei is alive: ", curr_time)
            time.sleep(1)
            if curr_time.hour >= 9 and curr_time.hour <= 14:
                if (curr_time.hour == 11 and curr_time.minute > 30) or curr_time.hour == 12:
                    continue
                elif curr_time.hour >= 15 and curr_time.minute > 1:
                    break
                elif (curr_time.hour == 9 and curr_time.minute >= 36) or curr_time.hour >= 10:

                    if curr_time.minute % 18 == 0 and curr_time.second % 39 == 0:
                        self.trend_reality.drop()
                        self.trader.driver.find_element_by_xpath('//*[@id="main"]/div/div[2]/div[1]/ul/li[1]/a').click()
                        buy_btn = self.trader.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="tabBody"]')))
                        if buy_btn:
                            res = self.trader.driver.find_element_by_xpath('//*[@id="tabBody"]')
                            res = res.text.split('\n')
                            for r in res:
                                per = r.split(' ')
                                if len(per) != 12:
                                    continue
                                # print(per)
                                # 更新当前实际持仓情况
                                self.trend_reality.insert_one({'code': self.chg_code_type(per[0]), 'hNum': per[2], 'uNum': per[3], 'money': per[6], 'cost': per[4], 'price': per[5], 'pct': per[8], 'yingkui': per[7]})

                                # 查询系统期望可用持仓情况（可用持仓情况只需要查询trade_rec, 不可用持仓则查看hasbuy）
                                mongo_res = self.trend_rec.find({'code': self.chg_code_type(per[0]), 'isSold': 0})
                                mongo_num = 0
                                if mongo_res:
                                    for m in mongo_res:
                                        mongo_num += m['left_num']

                                    if int(per[3]) > int(mongo_num) and per[0][0] not in ['5', '1']:
                                        # 卖出不一致仓位
                                        sold_num = int(per[3]) - int(mongo_num)
                                        sale_price = round(float(per[5]) * 0.99, 2)
                                        try:
                                            sold_num = 'all' if sold_num <= 100 else int(sold_num / 100) * 100
                                            with self.trade_lock:
                                                res = self.trader.auto_sale_chrome(self.chg_code_type(per[0]), sale_price, sold_num)
                                                self.logger.info(f"sold_point_get_reality_cangwei: {self.chg_code_type(per[0])}, curr_price:{float(per[5])}, num:{sold_num}, response:{res}")  # # send_notice('sold_point_get_reality_cangwei_success', f"sold_point_get_reality_cangwei: {self.chg_code_type(per[0])}, curr_price:{float(per[5])}, num:{sold_num}, response:{res}")  # time.sleep(5)
                                        except Exception as e:
                                            self.logger.error(f"sold_point_get_reality_cangwei: {self.chg_code_type(per[0])}, time:{curr_time}, sold_type:卖出不一致, e:{e}")  # # send_notice('sold_point_get_reality_cangwei_faild', f"sold_point_get_reality_cangwei: {self.chg_code_type(per[0])}, time:{curr_time}, sold_type:卖出不一致, e:{e}")  # time.sleep(5)

def main_trade():
    today = str(datetime.datetime.now().date())
    trend = Trend(today, '2022-09-15')

    thr1 = thr.Thread(target=trend.get_basic_data)
    thr2 = thr.Thread(target=trend.jk_buy)
    thr3 = thr.Thread(target=trend.jk_sale)
    thr4 = thr.Thread(target=trend.keep_login)
    thr5 = thr.Thread(target=trend.get_reality_cangwei)

    thr1.start()
    thr2.start()
    thr3.start()
    thr4.start()
    thr5.start()


if __name__ == '__main__':
    main_trade()