# Borrows heavily from git.py

import functools
import json
import os
import sublime
import sublime_plugin
import subprocess
import sys
import threading
import time
import re
# import types


def main_thread(callback, *args, **kwargs):
    # sublime.set_timeout gets used to send things onto the main thread
    # most sublime.[something] calls need to be on the main thread
    sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)

pkg_file_cache = {}


def pkg_file(directory, alternateDirectory):
    global pkg_file_cache

    # print directory
    # print alternateDirectory

    retval = False
    leaf_dir = directory

    if leaf_dir in pkg_file_cache and pkg_file_cache[leaf_dir]['expires'] > time.time():
        return pkg_file_cache[leaf_dir]['retval']

    while directory:
        path = os.path.join(directory, '.stitch_source')
        if os.path.exists(path):
            retval = path
            break
        parent = os.path.realpath(os.path.join(directory, os.path.pardir))
        if parent == directory:
            # /.. == /
            retval = False
            break
        directory = parent

    if alternateDirectory != '' and retval == False:
        retval = pkg_file(alternateDirectory, '')

    pkg_file_cache[leaf_dir] = {'retval': retval, 'expires': time.time() + 5}

    return retval


class CommandThread(threading.Thread):
    def __init__(self, command, on_done, working_dir="", **kwargs):
        threading.Thread.__init__(self)
        self.command = command
        self.on_done = on_done
        self.stdin = None
        self.stdout = subprocess.PIPE
        self.working_dir = working_dir
        self.kwargs = kwargs

    def run(self):
        try:
            os.chdir(self.working_dir)

            proc = subprocess.Popen(self.command,
                stdout=self.stdout, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                universal_newlines=True)

            output = proc.communicate(self.stdin)[0]

            if not output:
                output = ''

            main_thread(self.on_done, output, **self.kwargs)

        except subprocess.CalledProcessError, e:
            main_thread(self.on_done, e.returncode)
        except OSError, e:
            if e.errno == 2:
                main_thread(sublime.error_message,
                    "NPM binary could not be found.")
            else:
                raise e


class StitchCommand(object):

    def run_command(self, command, callback, **kwargs):

        if 'working_dir' not in kwargs:
            kwargs['working_dir'] = self.get_working_dir()

            thread = CommandThread(command, callback, **kwargs)
            thread.start()

    def _active_file_name(self):

        view = None

        if hasattr(self, 'view'):
            view = self.view
        else:
            view = self.window.active_view()

        if view and view.file_name() and len(view.file_name()) > 0:
            return view.file_name()

    def get_working_dir(self):
        file_name = self._active_file_name()
        if file_name:
            return os.path.dirname(file_name)
        else:
            return self.window.folders()[0]

    def is_enabled(self):

        if not hasattr(self, 'window'):
            self.window = self.view.window()

        if self._active_file_name() or len(self.window.folders()) == 1:
            return pkg_file(self.get_working_dir(), self.window.folders()[0])

    def get_source(self):

        pkg = pkg_file(self.get_working_dir(), self.window.folders()[0])

        if pkg:

            json_data = open(pkg)

            sourceMap = json.load(json_data)

            return sourceMap

        else:
            return None


class StitchTextCommand(StitchCommand, sublime_plugin.TextCommand):

    def run(self, edit):

        self.window = self.view.window()

        current_file = self.view.file_name()

        for region in self.view.sel():

            line = self.view.line(region)
            line_contents = self.view.substr(line)

            m = re.search("require([\s\(])[\'\"](.*)[\'\"]", line_contents)

            if m != None:
                name = m.group(2)
                self.with_name(name, current_file)


class StitchPanelCommand(StitchCommand):

    def show_panel(self):

        self.sourceMap = self.get_source()

        if self.sourceMap != None:

            self.window.show_quick_panel(self.sourceMap, self.panel_done)

    def panel_done(self, picked):

        if 0 > picked < len(self.sourceMap):
            return

        source = self.sourceMap[picked]

        self.with_source(source)


class StitchupOpenCommand(StitchPanelCommand, sublime_plugin.WindowCommand):

    def run(self):

        self.show_panel()

    def with_source(self, source):

        self.window.open_file(source[1])


class StitchupRequireCommand(StitchPanelCommand, sublime_plugin.TextCommand):

    def run(self, edit):

        self.edit = edit

        self.window = self.view.window()

        self.show_panel()

    def with_source(self, source):

        module_name = source[0]

        module_name = re.sub('\/index$', '', module_name)

        current_file = self.view.file_name()

        for source in self.sourceMap:

            if os.path.expanduser(source[1]) == current_file:

                root = os.path.split(source[0])[0]

                print root

                module_name = re.sub(root, '.', module_name)
                print module_name

        # root = os.path.split(current_module)[0]

        # print root

        # require_directive = "%s = require(%s)" % (module_candidate_name, get_path(module_rel_path))
        #     region = self.view.sel()[0]
        #     self.view.insert(edit, region.a, require_directive)
        #     self.view.run_command("reindent", {"single_line": True})
        require_directive = "require '%s'" % (module_name)

        region = self.view.sel()[0]

        self.view.insert(self.edit, region.a, require_directive)


class StitchupOpenRequireCommand(StitchTextCommand):

    def expand(self, name, root):

        results = []

        root = os.path.split(root)[0]

        parts = (root + '/' + name).split('/')

        for part in parts:
            if part == '..':
                results.pop()

            elif (part != '.') and (part != ''):
                results.append(part)

        return '/'.join(results)

    def with_name(self, name, current_file):

        relative = re.match('^\.', name)

        sourceMap = self.get_source()

        if relative != None:

            for source in sourceMap:

                if os.path.expanduser(source[1]) == current_file:
                    name = self.expand(name, source[0])

            # rel_path = os.path.relpath(name, current_file)

            # print name
            # print current_file
            # print rel_path

        for source in sourceMap:

            source_name = source[0]

            if (source_name == name) or (source_name == name + "/index"):
                self.window.open_file(source[1])
                return


def get_sublime_path():

    if sublime.platform() == 'osx':
        return '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl'
    elif sublime.platform() == 'linux':
        return open('/proc/self/cmdline').read().split(chr(0))[0]
    else:
        return sys.executable


def sublime_command_line(args):
    args.insert(0, get_sublime_path())
    return subprocess.Popen(args)
