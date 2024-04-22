from pygls.server import LanguageServer
from lsprotocol import types
import re
import argparse
import logging


parser = argparse.ArgumentParser(description="Specify port and address")
parser.add_argument("-p", "--port", type=int, help="Port number")
parser.add_argument("-a", "--address", type=str, default="localhost", help="Address")
parser.add_argument("--persistent", action="store_true", help="Persist after client disconnects")
args = parser.parse_args()
    
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server = LanguageServer("easyergo-server", "dev")

known_kws = [
    "easyblock",
    "name",
    "version",
    "homepage",
]


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def check_foo(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
    print("editing...")


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
async def check_bar(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
    print("saving...")


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def check_known_kws(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
    print("opening...")
    text_doc = ls.workspace.get_text_document(params.text_document.uri)

    all_kws = []
    for i, line in enumerate(text_doc.source.split('\n')):
        if m := re.match(r"^([A-Za-z0-9_]+)\s*=", line):
            all_kws.append((i, m[1]))
            diagnostics = []
    for i, kw in all_kws:
        if kw not in known_kws:
            diagnostics.append(types.Diagnostic(
                range=types.Range(
                    start=types.Position(i, 0),
                    end=types.Position(i, len(kw))
                ),
                message="Wrong Keyword Amigo.",
                source="EasyErgo"))

    ls.publish_diagnostics(text_doc.uri, diagnostics)

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

