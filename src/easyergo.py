from pygls.server import LanguageServer
from lsprotocol import types
import re

server = LanguageServer("easyergo-server", "dev")

known_kws = [
    "easyblock",
    "name",
    "version",
    "homepage",
]

@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def check_known_kws(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
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

server.start_tcp('127.0.0.1', 8000)
