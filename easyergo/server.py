import builtins
import difflib
import logging
import re
from glob import glob

from pygls.server import LanguageServer
from lsprotocol import types
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from easybuild.framework.easyconfig.default import DEFAULT_CONFIG as default_parameters
from easybuild.framework.easyconfig.easyconfig import get_easyblock_class, get_toolchain_hierarchy
from easybuild.framework.easyconfig.parser import EasyConfigParser, fetch_parameters_from_easyconfig
from easybuild.framework.easyconfig.templates import TEMPLATE_CONSTANTS
from easybuild.tools.options import EasyBuildOptions
from easybuild.tools.toolchain.utilities import search_toolchain
from easybuild.framework.easyconfig import constants as eb_constants

builtin_functions = set(attr for attr in dir(builtins) if callable(getattr(builtins, attr)))

PY_LANGUAGE = Language(tspython.language(), "python")
parser = Parser()
parser.set_language(PY_LANGUAGE)

# Fixed initializations of easybuild
eb_go = EasyBuildOptions(go_args=[])
robot_paths = eb_go.options.robot_paths
logging.debug("Using robot paths: %s", robot_paths)

all_constants = set(eb_constants.__all__ + [x[0] for x in TEMPLATE_CONSTANTS])

_, all_tc_classes = search_toolchain('')
subtoolchains = {tc_class.NAME: getattr(tc_class, 'SUBTOOLCHAIN', None) for tc_class in all_tc_classes}


def get_close_matches_icase(word, possibilities, *args, **kwargs):
    """ Case-insensitive version of difflib.get_close_matches """
    lpos = {p.lower(): p for p in possibilities}
    lmatches = difflib.get_close_matches(word.lower(), lpos.keys(), *args, **kwargs)
    return [lpos[m] for m in lmatches]


# Matches global keywards (TODO: also exclude single-char symbols)
query_global_kws = PY_LANGUAGE.query("""
((identifier) @kw (#not-match? @kw "^(local)?_.+"))
""")

# Matches dependency definitions
query_dep_spec = PY_LANGUAGE.query("""
(assignment
  left: (identifier)  @kw (#match? @kw "^(build)?dependencies$")
  right: (list (tuple .(_) @dep.name
                      .((_) @dep.version
                       .((_) @dep.versionsuffix
                        .((_) @dep.toolchain
                         .(_)* @dep.extra)?)?)? ) @dep.spec))
""") # get named keys for dep.spec matches, we always want them in order


def get_toolchains(ecdict):
    # Returns all compatible toolchains
    if 'toolchain' in ecdict:
        return [ecdict['toolchain']] + \
                [{'name': 'gfbf', 'version': '2023a'},
                 {'name': 'gompi', 'version': '2023a'},
                 {'name': 'GCC', 'version': '12.3.0'},
                 {'name': 'GCCcore', 'version': '12.3.0'}]  # TODO
    else:
        return None


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


def find_assignment(tree, name):
    return None # TODO: find assignment of variable named name


def extract(tree, names):
    # TODO search for names as assigned identifiers
    return {}


def check_variables(ls, uri, tree, eb_kw):
    all_known_ids = set(eb_kw) | set(default_parameters) | all_constants
    diagnostics = []
    for node, _ in query_global_kws.captures(tree.root_node):
        kw = node.text.decode('utf8')
        if kw not in default_parameters and kw not in eb_kw and kw not in all_constants:
            matches = get_close_matches_icase(kw, all_known_ids)
            message = "Did you mean: " + ",".join(matches) if matches else "Unknown variable"
            diagnostics.append(make_diagnostic(node, message))

    ls.publish_diagnostics(uri, diagnostics)


def check_dependencies(ls, uri, tree, ecdict, default_tcs):
    diagnostics = []
    for _, m in query_dep_spec.matches(tree.root_node):
        # Check at least that the tuple size makes sense
        if 'dep.spec' not in m: continue
        if 'dep.version' not in m or 'dep.extra' in m:
            diagnostics.append(make_diagnostic(m['dep.spec'], "Must have 2-4 elements exactly"))
            continue

        # fetch name, version, versionsuffix if they are all string, otherwise abort
        name_node, version_node = m['dep.name'], m['dep.version']
        if name_node.type != 'string' or version_node.type != 'string':
            continue
        name, version = eval(name_node.text), eval(version_node.text)
        
        # versionsuffix falls back to empty string, if not specified
        if 'dep.versionsuffix' in m:
            versionsuffix_node = m['dep.versionsuffix']
            if versionsuffix_node.type != 'string':
                continue
            else:
                versionsuffix = eval(versionsuffix_node.text)
        else:
            versionsuffix = ""

        if 'dep.toolchain' in m:
            if m['dep.toolchain'].text == b'SYSTEM':
                tcs = [{'name': 'system', 'version': 'system'}]
            else:
                continue  # give up on more complex toolchain spec here
        else:
            tcs = default_tcs

        matches, name_exists, name_suggestions = find_deps(name, versionsuffix, tcs)
        if matches:
            if not any(version in match for match in matches):
                diagnostics.append(make_diagnostic(version_node, 'Try ' + ','.join(matches)))
        else:
            if name_exists:
                diagnostics.append(make_diagnostic(version_node, 'No compatible version exist'))
            else:
                matches = get_close_matches_icase(name, name_suggestions)
                message = "Did you mean " + ",".join(matches) if matches else "Name not recognized"
                diagnostics.append(make_diagnostic(name_node, message))

    ls.publish_diagnostics(uri, diagnostics)


def check_filename(ls, uri, tree, ecdict):
    diagnostics = []
    # Check filename matching name, version, toolchain, versionsuffix
    filename = uri.split('/')[-1]
    # correct_filename = f'{name}-{version}-{toolchainname}-{toolchainversion}{versionsuffix}.eb'
    if 'name' in ecdict and not filename.startswith(f'{ecdict["name"]}-'):
        node = find_assignment(tree, 'name')
        if node:
            diagnostics.append(make_diagnostic(node, f"Does not match filename {filename}"))
        else:
            logging.warning("Couldn't locate name location in source")
    if 'version' in ecdict and not f'-{ecdict["version"]}-' in filename:
        node = find_assignment(tree, 'version')
        if node:
            diagnostics.append(make_diagnostic(node, f"Does not match filename {filename}"))
        else:
            logging.warning("Couldn't locate version location in source")
    if 'toolchain' in ecdict and 'name':
        toolchain = ecdict["toolchain"]
        if 'name' in toolchain and 'version' in toolchain and \
               toolchain["name"] != 'system' and \
           not f'-{toolchain["name"]}-{toolchain["version"]}' in filename:
            node = find_assignment(tree, 'toolchain')
            if node:
                diagnostics.append(make_diagnostic(node, f"Does not match filename {filename}"))
            else:
                logging.warning("Couldn't locate toolchain location in source")
    if 'versionsuffix' in ecdict:
        # TODO needs expanded template
        # not filename.endswith(f'{ecdict["versionsuffix"]}.eb'):
        if False:
            node = find_assignment(tree, 'versionsuffix')
            if node:
                diagnostics.append(make_diagnostic(node, f"Does not match filename {filename}"))
            else:
                logging.warning("Couldn't locate versionsuffix location in source")

    ls.publish_diagnostics(uri, diagnostics)


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

    logging.warning(f'found: {ecdict}')
       
    try:
        easyblock, name = ecdict['easyblock'], ecdict['name']
        app_class = get_easyblock_class(easyblock, name=name)
        eb_kw = app_class.extra_options()
    except:
        eb_kw = []

    default_tcs = get_toolchains(ecdict)

    check_variables(ls, text_doc.uri, tree, eb_kw)
    check_dependencies(ls, text_doc.uri, tree, ecdict, default_tcs)
    check_filename(ls, text_doc.uri, tree, ecdict)

