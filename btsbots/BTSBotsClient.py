#!/usr/bin/env python3
###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) Tavendo GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

# from pprint import pprint
import json
import time
from btsbots.MeteorClient import MeteorClient
from graphenebase.account import PrivateKey
from binascii import hexlify
import secp256k1
import hashlib
import struct
import math
import sys

try:
    import asyncio
except ImportError:
    import trollius as asyncio


def _is_canonical(sig):
    return (not (sig[0] & 0x80) and
            not (sig[0] == 0 and not (sig[1] & 0x80)) and
            not (sig[32] & 0x80) and
            not (sig[32] == 0 and not (sig[33] & 0x80)))


class RPCError(Exception):
    pass


class InvalidWifKey(Exception):
    pass


class LoginFailed(Exception):
    pass


class BTSBotsClient(object):
    def __init__(self, *args, **argv):
        # block interval is 3 seconds
        self.account = None
        self.key = None
        self.bi = 3
        self.isSync = False
        # the timestamp of recent two blocks
        self.sync_time = [[0, 0], [0, 1000]]
        self.spindle_char = ['|', '/', '-', '\\']
        self.spindle_index = 0
        self.ddp_client = MeteorClient(*args, **argv)
        self.ddp_client.on('added', self.added)
        self.ddp_client.on('changed', self.changed)
        # self.ddp_client.on('removed', self.removed)
        self.ddp_client.connect()
        self.ddp_client.subscribe('global_properties')

    def unsync(self):
        if not self.isSync:
            return
        self.isSync = False
        self.sync_time = [[0, 0], [0, 1000]]

    def spindle(self):
        sys.stdout.write(self.spindle_char[self.spindle_index])
        sys.stdout.flush()
        sys.stdout.write('\r')
        self.spindle_index = (self.spindle_index + 1) % len(self.spindle_char)

    def login(self, account, wifkey):
        try:
            self.key = PrivateKey(wifkey)
        except:
            raise InvalidWifKey
        p = bytes(self.key)
        pub_key = format(self.key.pubkey, 'BTS')

        auth_data = {
            "account": account,
            "site": 'btsbots.com',
            "time": time.time()
        }
        message = json.dumps(auth_data, sort_keys=True).encode('utf-8')
        digest = hashlib.sha256(message).digest()
        i = 0
        ndata = secp256k1.ffi.new("const int *ndata")
        ndata[0] = 0
        while True:
            ndata[0] += 1
            privkey = secp256k1.PrivateKey(p, raw=True)
            sig = secp256k1.ffi.new('secp256k1_ecdsa_recoverable_signature *')
            signed = secp256k1.lib.secp256k1_ecdsa_sign_recoverable(
                privkey.ctx,
                sig,
                digest,
                privkey.private_key,
                secp256k1.ffi.NULL,
                ndata
            )
            assert signed == 1
            signature, i = privkey.ecdsa_recoverable_serialize(sig)
            if _is_canonical(signature):
                i += 4   # compressed
                i += 27  # compact
                break
        # pack signature
        #
        sigstr = struct.pack("<B", i)
        sigstr += signature
        login_data = {
                "user": account,
                "pubkey": pub_key,
                "verify": {
                    "data": json.dumps(auth_data, sort_keys=True),
                    "signature": hexlify(sigstr).decode('ascii')
                    }
                }

        def logged_in(error, data):
            if error:
                print(error)
                # raise LoginFailed
            else:
                self.account = account
                self.ddp_client.subscribe('price')
                self.ddp_client.subscribe('login_order', params=[account])
                self.ddp_client.subscribe('login_balance', params=[account])

        self.ddp_client._login(login_data, logged_in)

    async def get_asset(self, assets):
        return await self.ddp_client.rpc('getAsset', [assets])

    async def keep_alive(self):
        # sent a null rpc to keep alive
        return await self.ddp_client.rpc('nullrpc', [])

    def onProfile(self, id, fields):
        # print('on profile:', id, fields)
        pass

    async def trade_bots(self):
        pass

    def onNewBlock(self, id, fields):
        self.sync_time[0] = self.sync_time[1].copy()
        self.sync_time[1] = [float(fields['T']), time.time()]
        time_offset = math.fabs((
            self.sync_time[0][0] - self.sync_time[0][1]) - (
                self.sync_time[1][0] - self.sync_time[1][1]))
        if time_offset < self.bi/2:
            self.isSync = True
        else:
            self.isSync = False
        # print("new block %s: %s" % (id, fields))
        # print(self.isSync, self.sync_time)

    def added(self, collection, id, fields):
        self.spindle()
        # print('* ADDED {} {}'.format(collection, id))
        # for key, value in fields.items():
        #     print('  - FIELD {} {}'.format(key, value))
        if collection == 'global_properties' and 'T' in fields:
            self.onNewBlock(id, fields)
        elif collection == 'users' and 'profile' in fields:
            self.onProfile(id, fields)

    def changed(self, collection, id, fields, cleared):
        self.spindle()
        # print('* changed {} {}'.format(collection, id))
        # for key, value in fields.items():
        #     print('  - FIELD {} {}'.format(key, value))
        if collection == 'global_properties' and 'B' in fields:
            self.onNewBlock(id, fields)
        elif collection == 'users' and 'profile' in fields:
            self.onProfile(id, fields)

    def removed(self, collection, id):
        print('* REMOVED {} {}'.format(collection, id))

    async def run(self):
        timer = 0
        while True:
            try:
                time_sleep = self.bi
                time_now = time.time()
                if self.isSync and time_now - self.sync_time[1][1] < self.bi:
                    time_next_run = self.sync_time[1][1] + self.bi*1.5
                    if self.account:
                        sys.stdout.write('*')
                        sys.stdout.flush()
                        sys.stdout.write('\r')
                        await self.trade_bots()
                    time_sleep = time_next_run - time.time()
                    if time_sleep < 0:
                        time_sleep = self.bi
                else:
                    self.unsync()
                await asyncio.sleep(time_sleep)
                timer += 1
                # keep alive every 60 seconds
                if timer % 20 == 0:
                    await self.keep_alive()
                # print(result)
            except Exception as e:
                print('unexcept error:', e)

if __name__ == '__main__':
    # import getpass

    account = 'test.iauth'
    wifkey = "5HvPnGfqMDrrdBGrtn2xRy1MQGbVgW5m8EWmXUNHBX9W4DzVGyM"
    # account = input('account name: ').strip()
    # wifkey = getpass.getpass('active private key for %s:' % account)
    client = BTSBotsClient('wss://btsbots.com/websocket', debug=False)
    # client = BTSBotsClient('ws://localhost:3000/websocket', debug=False)
    client.login(account, wifkey)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.run())
    loop.run_forever()
