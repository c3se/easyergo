#!/usr/bin/env python
import argparse
import logging
from easyergo import server


parser = argparse.ArgumentParser(description="Specify port and address")
parser.add_argument("-p", "--port", type=int, help="Port number")
parser.add_argument("-a", "--address", type=str, default="localhost", help="Address")
parser.add_argument("--persistent", action="store_true", help="Persist after client disconnects")
args = parser.parse_args()
    
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if args.persistent:
    # Why does this not work?
    # @server.feature(types.EXIT)
    # async def ignore_exit(ls, params):
    #    print("ignoring exit")
    #@server.feature(types.SHUTDOWN)
    #async def ignore_shutdown(ls, params):
    #    logger.info("ignoring shutdown")

    # Hack to make server persist
    server.lsp.fm.builtin_features['exit'] = lambda x: logger.info("ignoring exit")
    server.lsp.fm.builtin_features['shutdown'] = lambda x: logger.info("ignoring shutdown")
    server.lsp.connection_lost = lambda x: logger.info("ignoring lost connection")

if args.port is not None:
    server.start_tcp('127.0.0.1', 8000)
else:
    server.start_io()

