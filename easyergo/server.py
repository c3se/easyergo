import builtins
import difflib
import logging
import re
from glob import glob

from pygls.server import LanguageServer
from lsprotocol import types

from easybuild.framework.easyconfig.default import DEFAULT_CONFIG as default_parameters
from easybuild.framework.easyconfig.easyconfig import get_easyblock_class
from easybuild.framework.easyconfig.parser import EasyConfigParser, fetch_parameters_from_easyconfig
from easybuild.tools.options import EasyBuildOptions, CONFIG_ENV_VAR_PREFIX
from easybuild.tools.toolchain.utilities import search_toolchain

from easyergo.tsparser import EasyConfigTree, eb_constants

builtin_functions = set(attr for attr in dir(builtins) if callable(getattr(builtins, attr)))


# Fixed initializations of easybuild
eb_go = EasyBuildOptions(go_args=[], envvar_prefix=CONFIG_ENV_VAR_PREFIX)
robot_paths = eb_go.options.robot_paths
logging.debug("Using robot paths: %s", ':'.join(robot_paths))

_, all_tc_classes = search_toolchain('')
is_composite = {tc_class.NAME: len(tc_class.__bases__) > 1 for tc_class in all_tc_classes}
subtoolchains = {tc_class.NAME: getattr(tc_class, 'SUBTOOLCHAIN', None) for tc_class in all_tc_classes}
for key, val in subtoolchains.items():
    if val is None:
        val = []
    elif not isinstance(val, list):
        val = [val]
    # Only care about composites, rest if handled via deps anyway
    subtoolchains[key] = [v for v in val if (is_composite[v] if isinstance(v, str) else is_composite[v[0]])]


def find_easyconfigs(name, version):
    matches = []
    for robot_path in robot_paths:
        matches += glob(f'{robot_path}/{name[0].lower()}/{name}/{name}-{version}.eb') \
                + glob(f'{robot_path}/{name}/{name}-{version}.eb') \
                + glob(f'{robot_path}/{name}-{version}.eb')
    return matches


def get_toolchain_hierarchy(parent_toolchain):
    # Can't use the one from easybuild as it's to fragile and does a bunch of extra unwanted things to global state.
    # I also rewrote the logic here to consider toolchains
    bfs_queue = [parent_toolchain]
    tcs = [parent_toolchain]
    while bfs_queue:
        current_tc = bfs_queue.pop()
        current_tc_name, current_tc_version = current_tc['name'], current_tc['version']

        matches = find_easyconfigs(current_tc_name, current_tc_version)
        if not matches:
            continue
        ec = EasyConfigParser(matches[0])
        ecdict = ec.get_config_dict(validate=False)
        if 'dependencies' in ecdict:
            for dep in ecdict['dependencies']:
                if len(dep) == 2:
                    if dep[0] in subtoolchains:  # is a toolchain
                        logging.warning(f"Found dep {dep} as part of toolchain")
                        tc = {'name': dep[0], 'version': dep[1]}
                        tcs.append(tc)
                        bfs_queue.insert(0, tc)

        for subtoolchain_name in subtoolchains[current_tc_name]:
            logging.warning(f"Adding composite {subtoolchain_name} is composite")
            tcs.append({'name': subtoolchain_name, 'version': current_tc_version})
    return tcs


def get_close_matches_icase(word, possibilities, *args, **kwargs):
    """ Case-insensitive version of difflib.get_close_matches """
    lpos = {p.lower(): p for p in possibilities}
    lmatches = difflib.get_close_matches(word.lower(), lpos.keys(), *args, **kwargs)
    return [lpos[m] for m in lmatches]


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


def check_variables(ectree, eb_kw):
    all_known_ids = set(eb_kw) | set(default_parameters) | eb_constants.keys()
    diagnostics = []
    for node in ectree.nonlocal_var_nodes:
        kw = node.text.decode('utf8')
        if kw not in all_known_ids:
            matches = get_close_matches_icase(kw, all_known_ids)
            message = "Did you mean: " + ",".join(matches) if matches else "Unknown variable"
            diagnostics.append(make_diagnostic(node, message))

    return diagnostics


def check_dependencies(ectree, default_tcs):
    diagnostics = []
    for (node, children), value in zip(ectree.dep_nodes, ectree.dep_vals):
        if len(value)<2 or len(value)>4:
            diagnostics.append(make_diagnostic(node, "Must have 2-4 elements exactly"))
            continue

        name, version = value[:2]
        name_node, version_node = children[:2]
        versionsuffix = value[2] if len(value) > 2 else ""
        if len(value) > 3:
            if isinstance(value[3], dict):
                tcs = [value[3]]
            else:
                tcs = [{'name': value[3][0], 'version': value[3][1]}]
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

    return diagnostics


def check_filename(uri, ectree):
    # Check filename matching name, version, toolchain, versionsuffix
    # correct_filename = f'{name}-{version}-{toolchainname}-{toolchainversion}{versionsuffix}.eb'

    diagnostics = []
    filename = uri.split('/')[-1]
    ecdict = ectree.ecdict
    if 'name' in ecdict and not filename.startswith(f'{ecdict["name"]}-'):
        nodes = ectree.var_assign_map.get('name', None)
        if nodes:
            diagnostics.append(make_diagnostic(nodes[-1], f"Does not match filename {filename}"))
        else:
            logging.warning("Couldn't locate name location in source")
    if 'version' in ecdict and not f'-{ecdict["version"]}' in filename:
        nodes = ectree.var_assign_map.get('version', None)
        if nodes:
            diagnostics.append(make_diagnostic(nodes[-1], f"Does not match filename {filename}"))
        else:
            logging.warning("Couldn't locate version location in source")
    if 'toolchain' in ecdict and 'name':
        toolchain = ecdict["toolchain"]
        if 'name' in toolchain and 'version' in toolchain and \
               toolchain["name"] != 'system' and \
           not f'-{toolchain["name"]}-{toolchain["version"]}' in filename:
            nodes = ectree.var_assign_map.get('toolchain', None)
            if nodes:
                diagnostics.append(make_diagnostic(nodes[-1], f"Does not match filename {filename}"))
            else:
                logging.warning("Couldn't locate toolchain location in source")
    if 'versionsuffix' in ecdict:
        # TODO needs expanded template
        # not filename.endswith(f'{ecdict["versionsuffix"]}.eb'):
        if False:
            nodes = ectree.var_assign_map.get('versionsuffix', None)
            if nodes:
                diagnostics.append(make_diagnostic(nodes[-1], f"Does not match filename {filename}"))
            else:
                logging.warning("Couldn't locate versionsuffix location in source")

    return diagnostics


server = LanguageServer("easyergo-server", "dev")

@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def check_known_kws(ls,  params=types.DocumentDiagnosticParams):
    """Checks keywords agains know eb keywords"""

    # Extract as much information as possible:
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    try:
        ec = EasyConfigParser(rawcontent=text_doc.source)
        hints = ec.get_config_dict(validate=False)
    except:
        hints = {}
    ectree = EasyConfigTree(bytes(text_doc.source, 'utf-8'), hints)
    logging.warning(f'found: {ectree.ecdict}')

    try:
        easyblock, name = ectree.ecdict['easyblock'], ectree.ecdict['name']
        app_class = get_easyblock_class(easyblock, name=name)
        eb_kw = app_class.extra_options()
    except:
        eb_kw = []

    if 'toolchain' in ectree.ecdict:
        default_tcs = get_toolchain_hierarchy(ectree.ecdict['toolchain'])
    else:
        default_tcs = []
    logging.warning(f"Assuming toolchains: {default_tcs}")

    diagnostics = []
    diagnostics += check_variables(ectree, eb_kw)
    diagnostics += check_dependencies(ectree, default_tcs)
    diagnostics += check_filename(text_doc.uri, ectree)

    ls.publish_diagnostics(text_doc.uri, diagnostics)
