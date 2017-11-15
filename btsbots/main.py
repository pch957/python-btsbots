#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Program entry point"""

from __future__ import print_function

import argparse
import sys

from btsbots import metadata
from btsbots.TradeBots import TradeBots
import getpass

try:
    import asyncio
except ImportError:
    import trollius as asyncio


def main(argv):
    """Program entry point.

    :param argv: command-line arguments
    :type argv: :class:`list`
    """
    author_strings = []
    for name, email in zip(metadata.authors, metadata.emails):
        author_strings.append('Author: {0} <{1}>'.format(name, email))

    epilog = '''
{project} {version}

{authors}
URL: <{url}>
'''.format(
        project=metadata.project,
        version=metadata.version,
        authors='\n'.join(author_strings),
        url=metadata.url)

    arg_parser = argparse.ArgumentParser(
        prog=argv[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=metadata.description,
        epilog=epilog)
    arg_parser.add_argument(
        '-V', '--version',
        action='version',
        version='{0} {1}'.format(metadata.project, metadata.version))

    # account = 'test.iauth'
    # wifkey = "5HvPnGfqMDrrdBGrtn2xRy1MQGbVgW5m8EWmXUNHBX9W4DzVGyM"
    account = input('account name: ').strip()
    wifkey = getpass.getpass('active private key for %s:' % account)
    client = TradeBots('wss://btsbots.com/websocket', debug=False)
    # client = TradeBots('ws://localhost:3000/websocket', debug=False)
    client.login(account, wifkey)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.run())
    loop.run_forever()

    return 0


def entry_point():
    """Zero-argument entry point for use with setuptools/distribute."""
    raise SystemExit(main(sys.argv))


if __name__ == '__main__':
    entry_point()
