import re
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from easybuild.framework.easyconfig import constants as eb_constants
from easybuild.framework.easyconfig.templates import TEMPLATE_CONSTANTS

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

eb_constants = {k:eb_constants.__dict__[k] for k in eb_constants.__all__}
eb_constants.update({k:v[0] for k,v in TEMPLATE_CONSTANTS.items()})


def ec_property(fn, prop_name=None):
    """`@property`-like decorator for EC parse."""

    prop_name = "_" + fn.__name__ if prop_name is None else prop_name
    @property
    def ec_property_fn(self):
        if self.__dict__[prop_name] is None:
            fn(self)
            assert self.__dict__[prop_name] is not None
        return self.__dict__[prop_name]
    return ec_property_fn


class EasyConfigTree():
    """Representation of EasyConfig as syntax tree

    Several assumptions are made here:
    1. EasyConfig is shallow, no nested function definitions;
    2. assignments are simple, no handling of condition statments;
    3. each text file is parsed only once, so properties never change.

    """

    def __init__(self, text, hints={}):
        self.tree = parser.parse(text)
        self.hints = hints
        self._var_nodes = None
        self._nonlocal_var_nodes = None
        self._dep_nodes = None
        self._assign_nodes = None
        self._ecdict = None
        self._dep_vals = None
        self._var_assign_map = None

    @ec_property
    def var_nodes(self):
        """Find variable nodes

        This captures identifiers and method calls (e.g. `var.upper()`) to be
        matched against known EB variables.

        """
        self._var_nodes = set()
        self._attr_names = set()
        q = PY_LANGUAGE.query("""(
        (_ .(_) @first (identifier)? @other) @parent
        )""")
        for _, m in q.matches(self.tree.root_node):
            if m['first'][0].type == 'identifier':
                self._var_nodes.add(m['first'][0])
            if 'other' in m:
                if m['parent'][0].type!='attribute':
                    self._var_nodes.add(m['other'][0])
                else: # save a short list of  attributes for resolver
                    self._attr_names.add(m['other'][0].text.decode())

    @ec_property
    def var_assign_map(self):
        """Find variable assignments. """

        self._var_assign_map = {k.text.decode(): [] for k in self.var_nodes}
        q = PY_LANGUAGE.query("""(
        (assignment left: (identifier) @id ) @expr
        )""")
        for _, m in q.matches(self.tree.root_node):
            var_name = m['id'][0].text.decode()
            if var_name in self._var_assign_map:
                self._var_assign_map[var_name].append(m['expr'][0])

    @ec_property
    def dep_nodes(self):
        """All nodes that are dependency specifications. """
        if self._dep_nodes is None:
            self._dep_nodes = []
            q = PY_LANGUAGE.query("""(
            (assignment
            left: (identifier) @kw (#match? @kw "^(build)?dependencies$")
            right: (list (tuple ((_) ","?)+) @dep))
            )""")
            for _, m in q.matches(self.tree.root_node):
                if 'dep' in m:
                    children = m['dep'][0].children[1::2]
                    self._dep_nodes.append((m['dep'][0], children))

    @ec_property
    def nonlocal_var_nodes(self):
        """Variable nodes that are not named as a local variable. """
        self._nonlocal_var_nodes = set()
        for var_node in self.var_nodes:
            name = var_node.text
            if (len(name)>1
                and not name.startswith(b'_')
                and not name.startswith(b'local_')):
                self._nonlocal_var_nodes.add(var_node)

    def resolve_node(self, node, hints=None):
        """Attempt to derive the value of an expression node. We limit us to
        expressions where all child variables are available either as a
        eb_constant, or a hint.

        """

        if hints is None: hints=self.hints

        q = PY_LANGUAGE.query("""((identifier) @id)""")
        child_var_nodes = set(node[0] for node in q.captures(node).values())
        child_names = set(node.text.decode() for node in child_var_nodes)
        child_names = child_names.intersection(self.var_assign_map.keys())

        real_hints = eb_constants.copy()
        real_hints.update(hints)

        if len(child_names-real_hints.keys())==0:
            try:
                val = eval(node.text, real_hints)
                # Give up if the string seems to contain a template
                if not(isinstance(val, str) and re.match(r'.*%\(.*\)s', val)):
                    return val
            except:
                pass

        return "UNKNOWN"

    @ec_property
    def ecdict(self):
        """Construct the ecdict representation of the EasyConfig, this contains
        variables that are assigned ONLY ONCE, and the assignment is resolvable
        with resolve_node().

        """

        self._ecdict = self.hints.copy()
        for var_node in self.var_nodes:
            var_name = var_node.text.decode()
            if var_name in self._ecdict or len(self.var_assign_map[var_name])!=1:
                continue
            expr_node = self.var_assign_map[var_name][0].children[2]
            var_val = self.resolve_node(expr_node)
            if var_val != "UNKNOWN":
                self._ecdict[var_node.text.decode()]=var_val

    @ec_property
    def dep_vals(self):
        """All (build) dependencies in the EasyConfig. """

        self._dep_vals = []
        for _, children in self.dep_nodes:
            dep = tuple(self.resolve_node(child, self.ecdict) for child in children)
            self._dep_vals.append(dep)
