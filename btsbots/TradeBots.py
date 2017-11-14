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
        self.my_orders = []
        self.my_balances = []
        self.prices = []

    def onProfile(self, id, fields):
        print('updated profile')
        p = fields['profile']
        if 'bots_config' in p:
            self.bots_config = json.loads(p['bots_config'])
        if 'bots_limit' in p:
            self.bots_limit = json.loads(p['bots_limit'])
        if 'local_price' in p:
            self.local_price = json.loads(p['local_price'])

    async def trade_bots(self):
        self.my_orders = self.ddp_client.find('order', selector={'u': self.account})
        self.my_balances = self.ddp_client.find('balance', selector={'u': self.account})
        self.prices = self.ddp_client.find('price', selector={})

    async def cancel_all(self):
        ops = []
        for _e in self.my_orders:
            if _e['t'] == 7:
                _op = await self.build_cancel_order('1.7.%s' % _e['id'])
                ops.append(_op)
        await self.build_transaction(ops)

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
