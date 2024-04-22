from pygls.server import LanguageServer
from lsprotocol import types
import logging
import re
import difflib
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from easybuild.framework.easyconfig.default import DEFAULT_CONFIG as default_parameters
from easybuild.framework.easyconfig.parser import EasyConfigParser, fetch_parameters_from_easyconfig
from easybuild.framework.easyconfig.easyconfig import get_easyblock_class

PY_LANGUAGE = Language(tspython.language(), "python")
parser = tree_sitter.Parser()
parser.set_language(PY_LANGAUGE)

server = LanguageServer("easyergo-server", "dev")


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def check_known_kws(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
    text_doc = ls.workspace.get_text_document(params.text_document.uri)

    #ec = EasyConfigParser(rawcontent=text_doc.source)
    #ecdict = ec.get_config_dict()
    #name = ec['ec']['name']
    easyblock_name, name = fetch_parameters_from_easyconfig(text_doc.source, ['easyblock', 'name'])
    logging.debug(f'easyblock: {easyblock_name}, name: {name}')
    app_class = get_easyblock_class(easyblock_name, name=name)
    eb_kw = app_class.extra_options()
    all_known_parameters = set(eb_kw) | set(default_parameters)
    
    diagnostics = []
    # TODO: replace with parser
    all_kws = []
    for i, line in enumerate(text_doc.source.split('\n')):
        if line.startswith('local_') or line.startswith('_'):
            continue
        m = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
        if m:
            all_kws.append((i, m[1]))
    for i, kw in all_kws:
        if kw not in default_parameters and kw not in eb_kw:
            diagnostics.append(types.Diagnostic(
                range=types.Range(
                    start=types.Position(i, 0),
                    end=types.Position(i, len(kw))
                ),
                message="Did you mean: " + ",".join(difflib.get_close_matches(kw, all_known_parameters)),
                source="EasyErgo"))

    ls.publish_diagnostics(text_doc.uri, diagnostics)

