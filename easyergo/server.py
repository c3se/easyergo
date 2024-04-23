from pygls.server import LanguageServer
from lsprotocol import types
import builtins
import logging
import re
import difflib
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from easybuild.framework.easyconfig.default import DEFAULT_CONFIG as default_parameters
from easybuild.framework.easyconfig.parser import EasyConfigParser, fetch_parameters_from_easyconfig
from easybuild.framework.easyconfig.easyconfig import get_easyblock_class
import easybuild.framework.easyconfig

builtin_functions = set(attr for attr in dir(builtins) if callable(getattr(builtins, attr)))

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

def get_dependencies(tree):
    # Not very robust, assumes the simple case which is the case in 99% of easyconfigs
    dep_nodes = []
    for child in tree.root_node.children:
        if child.type == 'expression_statement':
            expr = child.children[0]
            if expr.type == 'assignment':
                var = expr.children[0].text
                if var == b'dependencies' or var == b'builddependencies':
                    if len(expr.children) != 3 or expr.children[2].type != 'list':
                        continue # Don't know what to do with this assignment
                    dep_nodes.append(expr.children[2])  # child 2 is RHS
    return dep_nodes


def make_diagnostic(node, message):
    # Wrap tree sitter node with a custom message
    return types.Diagnostic(
        range=types.Range(
            start=types.Position(*node.range.start_point),
            end=types.Position(*node.range.end_point)
        ),
        message=message,
        source="EasyErgo")


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
    logging.info(f'easyblock: {easyblock_name}, name: {name}')
    try:
        app_class = get_easyblock_class(easyblock_name, name=name)
        eb_kw = app_class.extra_options()
    except:
        eb_kw = []
    all_known_ids = set(eb_kw) | set(default_parameters) | set(all_constants)

    # Detect toolchain
    toolchain = fetch_parameters_from_easyconfig(text_doc.source, ['toolchain'])[0]
    print(toolchain)
    

    nodes = []
    tree = parser.parse(bytes(text_doc.source, 'utf8'))
    for node in get_identifiers(tree):
        ident = node.text.decode('utf8')
        if ident.startswith('local_') or ident.startswith('_') or ident in builtin_functions :
            continue
        nodes.append(node)

    diagnostics = []
    for node in nodes:
        kw = node.text.decode('utf8')
        if kw not in default_parameters and kw not in eb_kw and kw not in all_constants:
            matches = difflib.get_close_matches(kw, all_known_ids)
            message = "Did you mean: " + ",".join(matches) if matches else "Unknown variable"
            diagnostics.append(make_diagnostic(node, message))

    dep_nodes = get_dependencies(tree)
    for dep_node in dep_nodes:
        for node in dep_node.children:
            if node.type == 'tuple':
                values = node.children[1:-1:2]
                if len(values) == 2: # Just name and version
                    # diagnostics.append(make_diagnostic(node, "test"))
                    pass # TODO
                elif len(values) == 3: # name, version, versionsuffix
                    pass # TODO
                elif len(values) == 4: # name, version, versionsuffix, toolchain
                    pass # TODO
                else: # please make it stop
                    diagnostics.append(make_diagnostic(node, "Must have 2-4 elements exactly"))

    ls.publish_diagnostics(text_doc.uri, diagnostics)

