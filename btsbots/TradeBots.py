#!/usr/bin/env python
# -*- coding: utf-8 -*-
from btsbots.BTSBotsClient import BTSBotsClient
import json


class TradeBots(BTSBotsClient):
    def __init__(self, *args, **argv):
        super().__init__(*args, **argv)
        self.bots_config = {}
        self.bots_limit = {}
        self.local_price = {}
        # keep the cancel orders id to check if it's already done
        self.cancel_orders = []
        self.update_price_time = {}
        self.my_balance = {}
        self.prices = {}
        self.asset_blacklist = []

    async def build_cancel_order(self, order_id):
        self.cancel_orders.append(order_id)
        return await super().build_cancel_order(order_id)

    def onProfile(self, id, fields):
        print('update profile')
        p = fields['profile']
        if 'bots_config' in p:
            self.bots_config = json.loads(p['bots_config'])
        if 'bots_limit' in p:
            self.bots_limit = json.loads(p['bots_limit'])
        if 'local_price' in p:
            self.local_price = json.loads(p['local_price'])

    def get_my_balance(self, a, t):
        if a not in self.my_balance:
            return 0.0
        return self.my_balance[a][t]

    def add_my_balance(self, a, b0, b1):
        if a not in self.my_balance:
            self.my_balance[a] = [0.0, 0.0, 0.0]
        self.my_balance[a][1] += float(b0)
        self.my_balance[a][2] += float(b1)

    def get_orders_mine(self, a_s, a_b):
        _key = (a_s, a_b)
        if _key not in self.orders_mine:
            return []
        return self.orders_mine[_key]

    async def cancel_all_order(self):
        ops = []
        for market in self.orders_mine:
            for _e in self.orders_mine[market]:
                if _e['t'] == 7:
                    _op = await self.build_cancel_order(_e['id'])
                    ops.append(_op)
        await self.build_transaction(ops)

    def _get_price(self, a_s):
        if a_s in self.prices:
            if a_s.find("POLONIEX:USD") != -1:
                return self.prices[a_s]*self.prices['USD']
            if a_s.find("POLONIEX:BTC") != -1:
                return self.prices[a_s]*self.prices['BTC']
            return self.prices[a_s]
        return 0

    def get_price(self, a_s):
        scale = 1.0
        asset_ref = a_s
        asset_refs = []
        while asset_ref in self.local_price and self.local_price[asset_ref][1] not in asset_refs:
            scale *= self.local_price[asset_ref][0]
            asset_ref = self.local_price[asset_ref][1]
            asset_refs.append(asset_ref)
        return scale*self._get_price(asset_ref)

    def init_bots_data(self):
        self.orders_mine = {}
        self.orders_all = {}
        # there are 3 balance for each asset:
        # 0. total balance include: free, in order, in colle
        # 1. free balance, can use directely
        # 2. usable balance by bots, include: free, in order.
        self.my_balance = {}
        self.prices = {}
        cancel_done = True
        for e in self.ddp_client.find('price', selector={}):
            self.prices[e['a']] = float(e['p'])
        for e in self.ddp_client.find('balance', selector={'u': self.account}):
            b = float(e['b'])
            #
            self.my_balance[e['a']] = [b, b, b]
        for e in self.ddp_client.find('order', selector={}):
            # settlement
            if e['t'] == 4:
                if e['u'] == self.account:
                    self. add_my_balance(e['a'], -e['b'], -e['b'])
            # in order book
            elif e['t'] == 7:
                _key = (e['a_s'], e['a_b'])
                if _key not in self.orders_all:
                    self.orders_all[_key] = []
                self.orders_all[_key].append(e)
                if e['u'] == self.account:
                    if _key not in self.orders_mine:
                        self.orders_mine[_key] = []
                    if e['id'] in self.cancel_orders:
                        cancel_done = False
                    self.orders_mine[_key].append(e)
                    self.add_my_balance(e['a_s'], -e['b_s'], 0.0)
            # debt
            elif e['t'] == 8:
                if e['u'] == self.account:
                    self.add_my_balance(e['a_c'], -e['b_c'], -e['b_c'])
                    self.add_my_balance(e['a_d'], e['b_d'], e['b_d'])
        if cancel_done:
            self.cancel_orders = []

    async def check_asset_invalid(self, a_s):
        # in black list
        if a_s in self.asset_blacklist:
            return 0
        p_s = self.get_price(a_s)
        # no price
        if p_s == 0:
            return 0
        if a_s in self.ai:
            return p_s
        ret = await self.get_asset([a_s])
        if not ret[0]:
            self.asset_blacklist.append(a_s)
            print('[warnning] can not get asset info of %s, blacklist it' % a_s)
            return 0
        self.ai[a_s] = ret[0]
        return p_s

    async def trade_asset(self, ops_bots, a_s):
        controller = {}
        bots_config = self.bots_config
        p_s = await self.check_asset_invalid(a_s)
        if p_s == 0:
            return
        bUsable = self.get_my_balance(a_s, 1)
        bUsable2 = self.get_my_balance(a_s, 2)
        if a_s == 'BTS':
            keep_fees = 50/p_s  # keep 50 cny fees
            bUsable -= keep_fees
            bUsable2 -= keep_fees
            if bUsable < 0:
                bUsable = 0
            if bUsable2 < 0:
                bUsable2 = 0
        controller = {'b_usable': bUsable, 'price': p_s, 'market': {}}

        balance_total_order = 0.0
        # the first loop, calculate how many balance need to buy
        for a_b in bots_config[a_s]:
            p_b = await self.check_asset_invalid(a_b)
            if p_b == 0:
                continue
            if a_b in bots_config and a_s in bots_config[a_b]:
                sp1 = 1+bots_config[a_s][a_b]['spread']/100.0
                sp2 = 1+bots_config[a_b][a_s]['spread']/100.0
                if sp1*sp2 < 1.0:
                    print('[warnning] wrong spread for market %s/%s' % (a_s, a_b))
                    continue

            balance_limit_buy = float('inf')
            if a_b in self.bots_limit:
                balance_limit_buy = float(self.bots_limit[a_b])
            if 'balance_limit' in bots_config[a_s][a_b]:
                balance_limit_buy = float(bots_config[a_s][a_b]['balance_limit'])
            balance_limit_buy -= self.get_my_balance(a_b, 0)*p_b
            balance_limit_buy = max(balance_limit_buy, 0.0)
            balance_limit_order = min(
                    balance_limit_buy, float(bots_config[a_s][a_b]["balance_cny"]))
            balance_total_order += balance_limit_order

            controller['market'][a_b] = {
                'price': p_b, 'cancel': [], 'balance_limit_buy': balance_limit_buy,
                'balance_limit_order': balance_limit_order}

        # the second loop, calculate how many balance have for sell
        b_scale = 1.0
        if balance_total_order > bUsable2*p_s:
            b_scale *= bUsable2*p_s/balance_total_order
        for a_b in controller['market']:
            balance_limit_sell = controller['market'][a_b]["balance_limit_order"]*b_scale
            balance_limit_sell = max(balance_limit_sell, 10.0)
            p_b = controller['market'][a_b]['price']
            controller['market'][a_b]["balance_limit_order"] /= p_b
            controller['market'][a_b]["balance_limit_buy"] /= p_b
            controller['market'][a_b]["balance_limit_sell"] = balance_limit_sell/p_s
            if 't' not in bots_config[a_s][a_b]:
                bots_config[a_s][a_b]['t'] = 'mm1'
            if bots_config[a_s][a_b]['t'] == "mm1":
                await self.run_bots_mm1(ops_bots, controller, a_s, a_b)

    async def trade_bots(self):
        self.init_bots_data()
        # print(self.my_balance)
        # print(self.orders_mine)
        if self.get_my_balance('BTS', 1) < 1:
            print('[warnning] need more BTS for fees, try cancel all orders')
            await self.cancel_all_order()
            return
        if len(self.cancel_orders) > 0:
            return
        ops_bots = {'cancel': [], 'new': []}
        for a_s in self.bots_config:
            await self.trade_asset(ops_bots, a_s)
        await self.build_transaction(ops_bots['cancel'] + ops_bots['new'])

    async def bots_cancel_order(self, ops_bots, e, controller, a_s, a_b):
        print('[cancel order] %s/%s, id: %s' % (a_s, a_b, e['id']))
        controller['market'][a_b]['cancel'].append(e['id'])
        controller['b_usable'] += e['b_s']
        ops_bots['cancel'].append(await self.build_cancel_order(e['id']))

    async def bots_new_order(self, ops_bots, controller, amount, price, a_s, a_b):
        print('[new order] %s/%s, %s %s at price %s' % (
            a_s, a_b, amount, a_s, price))
        controller['b_usable'] -= amount
        ops_bots['new'].append(
            await self.build_limit_order(amount, price, a_s, a_b))

    async def check_order(self, ops_bots, controller, a_s, a_b, price, freq=60, price_limit=0.003):
        found = False
        price_in_cny = controller['price']
        amount = min(
            controller['market'][a_b]['balance_limit_buy']/price,
            controller['market'][a_b]['balance_limit_sell'])
        orders = self.get_orders_mine(a_s, a_b)
        for e in orders:
            # already in canceled list
            if e['id'] in controller['market'][a_b]['cancel']:
                continue
            if found:
                await self.bots_cancel_order(ops_bots, e, controller, a_s, a_b)
                print('reason: extra order')
                continue
            if amount <= 0.0 or \
                    e['b_s']/amount > 1.1 or \
                    e['b_s']/amount < 0.9 and controller['b_usable'] > 1.0/price_in_cny:
                await self.bots_cancel_order(ops_bots, e, controller, a_s, a_b)
                print('reason: balance %s change to %s' % (e['b_s'], amount))
                continue
            _key = (a_s, a_b)
            if _key not in self.update_price_time:
                self.update_price_time[_key] = 0
            if self.head_time-self.update_price_time[_key] > freq:
                if abs(e['p']/price-1) > price_limit:
                    await self.bots_cancel_order(ops_bots, e, controller, a_s, a_b)
                    print('reason: price %s change to %s' % (e['p'], price))
                    self.update_price_time[_key] = self.head_time
                    continue
            found = True
        if found:
            return
        # not valid order exit, make a new orders
        amount = min(amount, controller['b_usable'])
        if amount*price_in_cny < 1.0:  # too small, less than 1 CNY, don't sell
            return
        await self.bots_new_order(ops_bots, controller, amount, price, a_s, a_b)

    async def run_bots_mm1(self, ops_bots, controller, a_s, a_b):
        spread = float(self.bots_config[a_s][a_b]['spread'])/100.0
        price = controller['price']/controller['market'][a_b]['price']*(1+spread)
        await self.check_order(ops_bots, controller, a_s, a_b, price, 30)

    # async def test_fee(self):
    #     ops = []
    #     op1 = await self.build_limit_order(100, 1, 'BTS', 'CNY')
    #     # op2 = await self.build_limit_order(50, 2, 'CNY', 'BTS')
    #     # op3 = await self.build_cancel_order(0)
    #     ops = [op1]
    #     await self.build_transaction(ops)

if __name__ == '__main__':
    try:
        import asyncio
    except ImportError:
        import trollius as asyncio
    # import getpass

    account = 'test.iauth'
    wifkey = "5HvPnGfqMDrrdBGrtn2xRy1MQGbVgW5m8EWmXUNHBX9W4DzVGyM"
    # account = input('account name: ').strip()
    # wifkey = getpass.getpass('active private key for %s:' % account)
    client = TradeBots('wss://btsbots.com/websocket', debug=False)
    # client = TradeBots('ws://localhost:3000/websocket', debug=False)
    client.login(account, wifkey)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.run())
    loop.run_forever()
