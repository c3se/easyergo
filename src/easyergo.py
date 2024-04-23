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
import easybuild.framework.easyconfig

all_constants = easybuild.framework.easyconfig.constants.__all__ + \
                [x[0] for x in easybuild.framework.easyconfig.templates.TEMPLATE_CONSTANTS]

PY_LANGUAGE = Language(tspython.language(), "python")
parser = Parser()
parser.set_language(PY_LANGUAGE)

def get_identifiers(tree):
    cursor = tree.walk()
    # TODO: skip going into nodes that are of type "attribute"

    visited_children = False
    while True:
        if not visited_children:
            if cursor.node.type == 'identifier':
                yield cursor.node
            if not cursor.goto_first_child():
                visited_children = True
        elif cursor.goto_next_sibling():
            visited_children = False
        elif not cursor.goto_parent():
            break


server = LanguageServer("easyergo-server", "dev")


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def check_known_kws(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
    text_doc = ls.workspace.get_text_document(params.text_document.uri)

    # ec = EasyConfigParser(rawcontent=text_doc.source)
    # ecdict = ec.get_config_dict()
    # name = ec['ec']['name']
    easyblock_name, name = fetch_parameters_from_easyconfig(text_doc.source, ['easyblock', 'name'])
    logging.debug(f'easyblock: {easyblock_name}, name: {name}')
    app_class = get_easyblock_class(easyblock_name, name=name)
    eb_kw = app_class.extra_options()
    all_known_ids = set(eb_kw) | set(default_parameters) | set(all_constants)
    
    nodes = []
    tree = parser.parse(bytes(text_doc.source, 'utf8'))
    for node in get_identifiers(tree):
        if node.text.startswith(b'local_') or node.text.startswith(b'_'):
            continue
        nodes.append(node)

    diagnostics = []
    for node in nodes:
        kw = node.text.decode('utf8')
        if kw not in default_parameters and kw not in eb_kw and kw not in all_constants:
            diagnostics.append(types.Diagnostic(
                range=types.Range(
                    start=types.Position(*node.range.start_point),
                    end=types.Position(*node.range.end_point)
                ),
                message="Did you mean: " + ",".join(difflib.get_close_matches(kw, all_known_ids)),
                source="EasyErgo"))

    ls.publish_diagnostics(text_doc.uri, diagnostics)

