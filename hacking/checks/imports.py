#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import imp
import os
import re
import sys
import traceback

from hacking import core

RE_RELATIVE_IMPORT = re.compile('^from\s*[.]')

modules_cache = dict((mod, True) for mod in tuple(sys.modules.keys())
                     + sys.builtin_module_names)


@core.flake8ext
def hacking_import_rules(logical_line, physical_line, filename, noqa):
    r"""Check for imports.

    OpenStack HACKING guide recommends one import per line:
    Do not import more than one module per line

    Examples:
    Okay: from nova.compute import api
    H301: from nova.compute import api, utils


    Imports should usually be on separate lines.

    OpenStack HACKING guide recommends importing only modules:
    Do not import objects, only modules

    Examples:
    Okay: from os import path
    Okay: from os import path as p
    Okay: from os import (path as p)
    Okay: import os.path
    Okay: from nova.compute import rpcapi
    Okay: from os.path import dirname as dirname2  # noqa
    H302: from os.path import dirname as dirname2
    H302: from os.path import (dirname as dirname2)
    H303: from os.path import *
    H304: from .compute import rpcapi
    """
    # TODO(jogo): make the following doctests pass:
    #            H301: import os, sys
    # NOTE(afazekas): An old style relative import example will not be able to
    # pass the doctest, since the relativity depends on the file's locality
    # TODO(mordred: We need to split this into 4 different checks so that they
    # can be disabled by command line switches properly

    if noqa:
        return

    def is_module_for_sure(mod, search_path=sys.path):
        mod = mod.replace('(', '')  # Ignore parentheses
        try:
            mod_name = mod
            while '.' in mod_name:
                pack_name, _sep, mod_name = mod.partition('.')
                f, p, d = imp.find_module(pack_name, search_path)
                search_path = [p]
            imp.find_module(mod_name, search_path)
        except ImportError:
            try:
                # NOTE(vish): handle namespace modules
                if '.' in mod:
                    pack_name, mod_name = mod.rsplit('.', 1)
                    __import__(pack_name, fromlist=[mod_name])
                else:
                    __import__(mod)
            except ImportError:
                # NOTE(imelnikov): import error here means the thing is
                # not importable in current environment, either because
                # of missing dependency, typo in code being checked, or
                # any other reason. Anyway, we have no means to know if
                # it is module or not, so we return True to avoid
                # false positives.
                return True
            except Exception:
                # NOTE(jogo) don't stack trace if unexpected import error,
                # log and continue.
                traceback.print_exc()
                return False
            else:
                # NOTE(imelnikov): we imported the thing; if it was module,
                # it must be there:
                return mod in sys.modules
        return True

    def is_module(mod):
        """Checks for non module imports."""
        if mod in modules_cache:
            return modules_cache[mod]
        res = is_module_for_sure(mod)
        modules_cache[mod] = res
        return res

    current_path = os.path.dirname(filename)
    current_mod = os.path.basename(filename)
    if current_mod[-3:] == ".py":
        current_mod = current_mod[:-3]

    split_line = logical_line.split()
    split_line_len = len(split_line)
    if (split_line_len > 1 and split_line[0] in ('import', 'from') and
            not core.is_import_exception(split_line[1])):
        pos = logical_line.find(',')
        if pos != -1:
            if split_line[0] == 'from':
                yield pos, "H301: one import per line"
            return  # ',' is not supported by the H302 checker yet
        pos = logical_line.find('*')
        if pos != -1:
            yield pos, "H303: No wildcard (*) import."
            return

        if split_line_len in (2, 4, 6) and split_line[1] != "__future__":
            if 'from' == split_line[0] and split_line_len > 3:
                mod = '.'.join((split_line[1], split_line[3]))
                if core.is_import_exception(mod):
                        return
                if RE_RELATIVE_IMPORT.search(logical_line):
                    yield logical_line.find('.'), (
                        "H304: No relative imports. '%s' is a relative import"
                        % logical_line)
                    return

                if not is_module(mod):
                    yield 0, ("H302: import only modules."
                              "'%s' does not import a module" % logical_line)
                return

        # NOTE(afazekas): import searches first in the package
        # The import keyword just imports modules
        # The guestfs module now imports guestfs
        mod = split_line[1]
        if (current_mod != mod and not is_module(mod) and
                is_module_for_sure(mod, [current_path])):
            yield 0, ("H304: No relative imports."
                      " '%s' is a relative import" % logical_line)


# Get the location of a known stdlib module
_, p, _ = imp.find_module('imp')
stdlib_path_prefix = os.path.dirname(p)
module_cache = dict()


def _get_import_type(module):
    mod_base, _, _ = module.partition('.')
    if mod_base in module_cache:
        return module_cache[mod_base]

    def cache_type(module_type):
        module_cache[mod_base] = module_type
        return module_type

    # First check if the module is local
    try:
        imp.find_module(mod_base, ['.'])
        # If the previous line succeeded then it must be a project module
        return cache_type('project')
    except ImportError:
        pass

    try:
        _, path, _ = imp.find_module(mod_base)
    except ImportError:
        return cache_type('third-party')

    if path is None:
        # NOTE(imelnikov): python 3 returns None for path of builtin
        # modules, like sys or builtin; they are definitely stdlib
        return cache_type('stdlib')
    if 'site-packages' in path or 'dist-packages' in path:
        return cache_type('third-party')
    if (path.startswith(stdlib_path_prefix) or
            path.startswith(sys.prefix) or
            path == module):
        return cache_type('stdlib')
    return cache_type('third-party')


@core.flake8ext
def hacking_import_groups(logical_line, blank_lines, previous_logical,
                          indent_level, previous_indent_level, physical_line,
                          noqa):
    r"""Check that imports are grouped correctly.

    OpenStack HACKING guide recommendation for imports:
    imports grouped such that Python standard library imports are together,
    third party library imports are together, and project imports are
    together

    Okay: import os\nimport sys\n\nimport six\n\nimport hacking
    Okay: import six\nimport znon_existent_package
    H305: import hacking\nimport os
    H305: import os\nimport six
    H305: import os\nimport znon_existent_package
    """
    if (noqa or blank_lines > 0 or
            indent_level != previous_indent_level):
        return

    normalized_line = core.import_normalize(logical_line.strip()).split()
    normalized_previous = core.import_normalize(previous_logical.
                                                strip()).split()
    if normalized_line and normalized_line[0] == 'import':
        current_type = _get_import_type(normalized_line[1])
        if normalized_previous and normalized_previous[0] == 'import':
            previous_type = _get_import_type(normalized_previous[1])
            if current_type != previous_type:
                yield(0, 'H305: imports not grouped correctly '
                      '(%s: %s, %s: %s)' %
                      (normalized_previous[1], previous_type,
                       normalized_line[1], current_type))


@core.flake8ext
def hacking_import_alphabetical(logical_line, blank_lines, previous_logical,
                                indent_level, previous_indent_level):
    r"""Check for imports in alphabetical order.

    OpenStack HACKING guide recommendation for imports:
    imports in human alphabetical order

    Okay: import os\nimport sys\n\nimport nova\nfrom nova import test
    Okay: import os\nimport sys
    H306: import sys\nimport os
    """
    # handle import x
    # use .lower since capitalization shouldn't dictate order
    split_line = core.import_normalize(logical_line.strip()).lower().split()
    split_previous = core.import_normalize(previous_logical.
                                           strip()).lower().split()

    if blank_lines < 1 and indent_level == previous_indent_level:
        length = [2, 4]
        if (len(split_line) in length and len(split_previous) in length and
                split_line[0] == "import" and split_previous[0] == "import"):
            if split_line[1] < split_previous[1]:
                yield (0, "H306: imports not in alphabetical order (%s, %s)"
                       % (split_previous[1], split_line[1]))


class ImportGroupData:
    """A class to hold persistent state data for import group checks.

    To verify import grouping, it is necessary to know the current group
    for the current file.  This can not always be known solely from the
    current and previous line, so this class can be used to keep track.
    """

    # NOTE(bnemec): *args is needed because the test code tries to run this
    # as a flake8 check and passes an argument to it.
    def __init__(self, *args):
        self.current_group = None
        self.current_filename = None
        self.current_import = None


together_data = ImportGroupData()


@core.flake8ext
def hacking_import_groups_together(logical_line, blank_lines, indent_level,
                                   previous_indent_level, line_number,
                                   physical_line, filename, noqa):
    r"""Check that like imports are grouped together.

    OpenStack HACKING guide recommendation for imports:
    Imports should be grouped together by type.

    Okay: import os\nimport sys
    Okay: try:\n    import foo\nexcept ImportError:\n    pass\n\nimport six
    H307: import os\n\nimport sys
    """
    if line_number == 1 or filename != together_data.current_filename:
        together_data.current_group = None
    together_data.current_filename = filename

    if noqa:
        return

    normalized_line = core.import_normalize(logical_line.strip()).split()
    if normalized_line and normalized_line[0] == 'import':
        current_type = _get_import_type(normalized_line[1])
        previous_import = together_data.current_import
        together_data.current_import = normalized_line[1]
        matched = current_type == together_data.current_group
        together_data.current_group = current_type
        if (matched and indent_level == previous_indent_level and
                blank_lines >= 1):
            yield(0, 'H307: like imports should be grouped together (%s and '
                  '%s from %s are separated by whitespace)' %
                  (previous_import,
                   together_data.current_import,
                   current_type))
