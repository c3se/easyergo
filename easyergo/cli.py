import logging
logger = logging.getLogger("easyergo:cli")

def main():
    import argparse
    from easyergo.server import server

    parser = argparse.ArgumentParser(description="Specify port and address")
    parser.add_argument("-p", "--port", type=int, help="Port number")
    parser.add_argument("-a", "--address", type=str, default="localhost", help="Address")
    parser.add_argument("--persistent", action="store_true", help="Persist after client disconnects")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()

    if args.persistent or args.debug:
        # Why does this not work?
        # @server.feature(types.EXIT)
        # async def ignore_exit(ls, params):
        #     print("ignoring exit")
        # @server.feature(types.SHUTDOWN)
        # async def ignore_shutdown(ls, params):
        #     logger.info("ignoring shutdown")

        # Hack to make server persist
        server.lsp.fm.builtin_features['exit'] = lambda x: logger.info("ignoring exit")
        server.lsp.fm.builtin_features['shutdown'] = lambda x: logger.info("ignoring shutdown")
        server.lsp.connection_lost = lambda x: logger.info("ignoring lost connection")

    if args.debug:
        logging.basicConfig(level=logging.INFO)

    if args.port is not None:
        server.start_tcp(args.address, args.port)

    else:
        server.start_io()


if __name__ == "__main__":
    main()
