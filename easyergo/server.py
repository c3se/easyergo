from pygls.server import LanguageServer
from lsprotocol import types
import builtins
import logging
import re
import difflib
import tree_sitter_python as tspython
from glob import glob
from tree_sitter import Language, Parser

from easybuild.framework.easyconfig.default import DEFAULT_CONFIG as default_parameters
from easybuild.framework.easyconfig.parser import EasyConfigParser, fetch_parameters_from_easyconfig
from easybuild.framework.easyconfig.easyconfig import get_easyblock_class, get_toolchain_hierarchy
from easybuild.tools.toolchain.utilities import search_toolchain
import easybuild.framework.easyconfig

builtin_functions = set(attr for attr in dir(builtins) if callable(getattr(builtins, attr)))

all_constants = easybuild.framework.easyconfig.constants.__all__ + \
                [x[0] for x in easybuild.framework.easyconfig.templates.TEMPLATE_CONSTANTS]

PY_LANGUAGE = Language(tspython.language(), "python")
parser = Parser()
parser.set_language(PY_LANGUAGE)

_, all_tc_classes = search_toolchain('')
subtoolchains = {tc_class.NAME: getattr(tc_class, 'SUBTOOLCHAIN', None) for tc_class in all_tc_classes}

robot_paths = ['/apps/easybuild-easyconfigs/easybuild/easyconfigs/']


def get_close_matches_icase(word, possibilities, *args, **kwargs):
    """ Case-insensitive version of difflib.get_close_matches """
    lword = word.lower()
    lpos = {p.lower(): p for p in possibilities}
    lmatches = difflib.get_close_matches(lword, lpos.keys(), *args, **kwargs)
    return [lpos[m] for m in lmatches]


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


def find_deps(name, versionsuffix, tcs):
    name_exists = True
    name_suggestions = []
    matches = []
    for robot_path in robot_paths:
        for tc in tcs:
            if tc['name'] == 'system':
                matches += glob(f'{robot_path}/{name[0].lower()}/{name}/{name}-*{versionsuffix}.eb')
                matches += glob(f'{robot_path}/{name}-*{versionsuffix}.eb')
            else:
                tcname = tc['name'] + '-' + tc['version']
                matches += glob(f'{robot_path}/{name[0].lower()}/{name}/{name}-*-{tcname}{versionsuffix}.eb')
                matches += glob(f'{robot_path}/{name}-*-{tcname}{versionsuffix}.eb')
    if not matches:  # Check if name exists at all
        name_exists = bool(glob(f'{robot_path}/{name[0].lower()}/{name}/')) or bool(glob(f'{robot_path}/{name}-*.eb'))
        if not name_exists:
            name_suggestions = [m.split('/')[-2] for m in glob(f'{robot_path}/{name[0].lower()}/*/')]

    matches = [match.split('/')[-1] for match in matches]
    return matches, name_exists, name_suggestions


def make_diagnostic(node, message):
    # Wrap tree sitter node with a custom message
    return types.Diagnostic(
        range=types.Range(
            start=types.Position(*node.range.start_point),
            end=types.Position(*node.range.end_point)
        ),
        message=message,
        source="EasyErgo")


def extract(tree, names):
    # TODO search for names as assigned identifiers
    return {}


server = LanguageServer("easyergo-server", "dev")

@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def check_known_kws(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""
    
    # Extract as much information as possible:
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    tree = parser.parse(bytes(text_doc.source, 'utf8'))
    try:
        ec = EasyConfigParser(rawcontent=text_doc.source)
        ecdict = ec.get_config_dict(validate=False)
    except:
        ecdict = extract(tree, ['easyblock', 'name', 'version', 'toolchain'])

    logging.info(f'found: {ecdict}')
       
    try:
        easyblock, name = ecdict['easyblock'], ecdict['name']
        app_class = get_easyblock_class(easyblock, name=name)
        eb_kw = app_class.extra_options()
    except:
        eb_kw = []

    # Detect toolchain
    if 'toolchain' in ecdict:
        # TODO:
        default_tcs = [{'name': 'foss', 'version': '2023a'},
                       {'name': 'gfbf', 'version': '2023a'},
                       {'name': 'gompi', 'version': '2023a'},
                       {'name': 'GCC', 'version': '12.3.0'},
                       {'name': 'GCCcore', 'version': '12.3.0'}]
    else:
        default_tcs = None

    all_known_ids = set(eb_kw) | set(default_parameters) | set(all_constants)

    diagnostics = []

    # Check options and constants
    nodes = []
    for node in get_identifiers(tree):
        ident = node.text.decode('utf8')
        if ident.startswith('local_') or ident.startswith('_') or ident in builtin_functions :
            continue
        nodes.append(node)

    for node in nodes:
        kw = node.text.decode('utf8')
        if kw not in default_parameters and kw not in eb_kw and kw not in all_constants:
            matches = get_close_matches_icase(kw, all_known_ids)
            message = "Did you mean: " + ",".join(matches) if matches else "Unknown variable"
            diagnostics.append(make_diagnostic(node, message))

    # Check dependency names and versions
    dep_nodes = get_dependencies(tree)
    for dep_node in dep_nodes:
        for node in dep_node.children:
            if node.type == 'tuple':
                values = node.children[1:-1:2]
                if len(values) < 2:
                    diagnostics.append(make_diagnostic(node, "Must have 2-4 elements exactly"))
                    continue
            
                if values[0].type != 'string' or values[1].type != 'string':
                    continue  # ignoring parameterized entries

                name, version = eval(values[0].text), eval(values[1].text)
                versionsuffix, tcs = '', default_tcs
                if len(values) >= 3:
                    versionsuffix = eval(values[2].text)

                if any('%' in x for x in (name, version, versionsuffix)):
                    continue  # can't deal with templates

                if len(values) >= 4:
                    if values[3].text == b'SYSTEM':
                        tcs = [{'name': 'system', 'version': 'system'}]
                    else:
                        continue  # tcs = [eval(values[3].text)]  # Just giving up for now

                matches, name_exists, name_suggestions = find_deps(name, versionsuffix, tcs)
                if matches:
                    if not any(version in match for match in matches):
                        diagnostics.append(make_diagnostic(values[1], 'Try ' + ','.join(matches)))
                else:
                    if name_exists:
                        diagnostics.append(make_diagnostic(values[1], 'No compatible version exist'))
                    else:
                        matches = get_close_matches_icase(name, name_suggestions)
                        message = "Did you mean " + ",".join(matches) if matches else "Name not recognized"
                        diagnostics.append(make_diagnostic(values[0], message))

    # Check filename matching name, version, toolchain, versionsuffix
    filename = params.text_document.uri.split('/')[-1]
    for node in nodes:
        if node.text == b'name':
            pass #diagnostics.append(make_diagnostic(node, "Does not match filename"))
        elif node.text == b'version':
            pass #diagnostics.append(make_diagnostic(node, "Does not match filename"))
        elif node.text == b'toolchain':
            pass #diagnostics.append(make_diagnostic(node, "Does not match filename"))

    ls.publish_diagnostics(text_doc.uri, diagnostics)

