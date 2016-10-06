#!/usr/bin/env python

# automatically generate Makefile dependencies for Fortran 90 source.
#
# this will output all the dependency pairs amongst the source files.

from __future__ import print_function

import sys
import re
import os
import argparse
import shlex
import subprocess

# modules to ignore in the dependencies
IGNORES = ["iso_c_binding", "iso_fortran_env"]

# regular expression for "{}module{}name", where {} can be any number
# of spaces.  We use 4 groups here, denoted by (), so the name of the
# module is the 4th group
module_re = re.compile("( )(module)(\s+)((?:[a-z][a-z_0-9]+))",
                       re.IGNORECASE|re.DOTALL)

# regular expression for "{}module{}procedure{}name"
module_proc_re = re.compile("( )(module)(\s+)(procedure)(\s+)((?:[a-z][a-z_0-9]+))",
                            re.IGNORECASE|re.DOTALL)

# regular expression for "{}use{}modulename...".  Note this will work for
# use modulename, only: stuff, other stuff'
# see (txt2re.com)
use_re = re.compile("( )(use)(\s+)((?:[a-z_][a-z_0-9]+))",
                    re.IGNORECASE|re.DOTALL)


def run(command, stdin=False, outfile=None):
    """ run a command in the unix shell """

    # shlex.split will preserve inner quotes
    sin = None
    if stdin: sin = subprocess.PIPE
    p0 = subprocess.Popen(command, stdin=sin, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, shell=True)

    stdout0, stderr0 = p0.communicate()
    if stdin: p0.stdin.close()
    rc = p0.returncode
    p0.stdout.close()

    if outfile is not None:
        try: cf = open(outfile, "w")
        except IOError:
            sys.exit("ERROR: unable to open file for writing: {}".format(outfile))
        else:
            for line in stdout0:
                cf.write(line)
            cf.close()

    return stdout0, rc


class Preprocessor(object):
    """ hold the information about preprocessing """

    def __init__(self, temp_dir=None, cpp_cmd=None,
                 defines=None, f90_preprocess=None):

        self.temp_dir = temp_dir
        self.cpp_cmd = cpp_cmd
        self.defines = defines
        self.f90_preprocess = f90_preprocess

    def preprocess(self, sf):
        """ preprocess the file described by a SourceFile object sf """

        # we want to do:
        # $(FORT_CPP) $(CPPFLAGS) $< | $(F90PREP) > $(f77TempDir)/$*.f90
        # we output to the temporary directory

        processed_file = "{}/TEST-{}".format(self.temp_dir, os.path.basename(sf.name))

        command = "{} {} {} | {}".format(self.cpp_cmd, self.defines, 
                                         sf.name, self.f90_preprocess)

        stdout, rc = run(command, outfile=processed_file)

        sf.cpp_name = processed_file


class SourceFile(object):
    """ hold information about one of the .f90/.F90 files """

    def __init__(self, filename):

        self.name = filename

        # do we need to be preprocessed?  We'll use the convention
        # that .F90 = yes, .f90 = no
        self.ext = os.path.splitext(filename)[1]

        if self.ext in [".F90", ".F95", ".F03"]:
            self.preprocess = True
        else:
            self.preprocess = False

        # when we preprocess, the output file has a different name
        self.cpp_name = None


    def search_name(self):
        """return the file name we use for searching -- this is the
        preprocessed file if it exists"""

        if self.cpp_name is not None:
            search_file = self.cpp_name
        else:
            search_file = self.name

        return search_file


    def obj(self):
        """ the name of the object file we expect to be produced -- this
        will always be based on the original name -- we do not compile the
        preprocessed files """
        return self.name.replace(self.ext, ".o")


    def defined_modules(self):
        """determine what modules this file provides -- we work off of the
        preprocessed file if it exists."""

        defines = []

        with open(self.search_name(), "r") as f:

            for line in f:

                # strip off the comments
                idx = line.find("!")
                line = line[:idx]

                # we want a module definition itself, not a 'module procedure'
                rebreak = module_re.search(line)
                rebreak2 = module_proc_re.search(line)
                if rebreak and not rebreak2:
                    defines.append(rebreak.group(4))

        return defines


    def needed_modules(self):
        """determine what modules this file needs.  Assume only one use
           statement per line.  Ignore any only clauses.  We work off
           of the preprocessed file if it exists."""

        depends = []

        with open(self.search_name(), "r") as f:

            for line in f:

                # strip off the comments
                idx = line.find("!")
                line = line[:idx]

                rebreak = use_re.search(line)
                if rebreak:
                    used_module = rebreak.group(4)
                    if used_module not in IGNORES:
                        depends.append(used_module)

        # remove duplicates
        depends = list(set(depends))

        return depends


def doit(prefix, search_path, files, cpp):

    # module_files is a dictionary where the keys are the name of the
    # module (as it appears in Fortran code) and the value associated
    # with the key is the name of the object file that provides the
    # module.
    module_files = {}

    # all_files is a list of SourceFile objects
    all_files = []

    # find the locations of all the files, given an (optional) search
    # path and preprocess them if necessary
    for cf in files:

        # find the file in the first part of the search path it exists
        if len(search_path) > 0:
            for p in search_path:
                full_file = "{}/{}".format(p, cf)
                if os.path.isfile(full_file):
                    break
        else:
            full_file = cf

        sf = SourceFile(full_file)

        # preprocess, if necessary
        if sf.preprocess:
            cpp.preprocess(sf)

        all_files.append(sf)

    # for each file, figure out what modules they define and add those to
    # the module_files dictionary -- the module provided is the "key" and
    # the value is the object file corresponding to the source file that
    # holds the module definition
    for sf in all_files:
        provides = sf.defined_modules()

        for p in provides:
            module_files[p] = sf.obj()


    # go back through the files now and look for the use statements
    # to figure out what modules each file requires
    for sf in all_files:
        depends = sf.needed_modules()

        for d in depends:
            print("{}: {}".format(
                prefix+os.path.basename(sf.obj()),
                prefix+os.path.basename(module_files[d])))

        print(" ")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix",
                        help="prefix to prepend to each dependency pair, e.g., for a build directory",
                        default="")
    parser.add_argument("--search_path",
                        help="ordered path to search for the files",
                        default="")
    parser.add_argument("--cpp",
                        help="apply the C preprocessor first?",
                        default="")
    parser.add_argument("--f90_preprocess",
                        help="command to pipe cpp output to for additional Fortran preprocessing",
                        default="")
    parser.add_argument("--temp_dir",
                        help="directory to put temporary preprocessed files",
                        default="")
    parser.add_argument("--defines",
                        help="defines to send to preprocess the files",
                        default="")
    parser.add_argument("files", metavar="source files", type=str, nargs="*",
                        help="F90 source files to find dependencies amongst")

    args = parser.parse_args()

    if args.prefix != "":
        prefix = "{}/".format(os.path.normpath(args.prefix))

    # create a preprocessor object
    cpp = Preprocessor(temp_dir=args.temp_dir, cpp_cmd=args.cpp,
                       defines=args.defines, f90_preprocess=args.f90_preprocess)

    doit(prefix, args.search_path.split(), args.files, cpp)