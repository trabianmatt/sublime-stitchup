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
import types


def main_thread(callback, *args, **kwargs):
    # sublime.set_timeout gets used to send things onto the main thread
    # most sublime.[something] calls need to be on the main thread
    sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)


npm_root_cache = {}


def npm_root(directory):
    global npm_root_cache

    retval = False
    leaf_dir = directory

    if leaf_dir in npm_root_cache and npm_root_cache[leaf_dir]['expires'] > time.time():
        return npm_root_cache[leaf_dir]['retval']

    while directory:
        if os.path.exists(os.path.join(directory, 'package.json')):
            retval = directory
            break
        parent = os.path.realpath(os.path.join(directory, os.path.pardir))
        if parent == directory:
            # /.. == /
            retval = False
            break
        directory = parent

    npm_root_cache[leaf_dir] = {'retval': retval, 'expires': time.time() + 5}

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


class NpmCommand(object):

    def run_command(self, command, callback, **kwargs):

        if 'working_dir' not in kwargs:
            kwargs['working_dir'] = self.get_working_dir()

            thread = CommandThread(command, callback, **kwargs)
            thread.start()


class NpmWindowCommand(NpmCommand, sublime_plugin.WindowCommand):

    def _active_file_name(self):
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
        if self._active_file_name() or len(self.window.folders()) == 1:
            return npm_root(self.get_working_dir())


class NpmPackageCommand(NpmWindowCommand):

    def run(self):

        self.run_command(['npm', 'ls', '-l', '--json'], self.list_done)

    def list_done(self, results):

        try:
            package_info = json.loads(results)
        except (ValueError):
            sublime.error_message(('%s: Error parsing JSON from ' +
                'npm ls.') % (__name__))

        self.package_info = package_info

        self.all_dependencies = {}

        self.package_list = []

        self.add_dependencies(self.package_info.get('dependencies'))

        self.window.show_quick_panel(self.package_list, self.panel_done)

    def add_dependencies(self, dependencies):

        for package in dependencies:

            package_entry = [package]

            info = dependencies.get(package)

            if type(info) == types.DictType:

                path = info.get('path')
                description = info.get('description')

                # print path

                if path != None:

                    if description != None:
                        package_entry.append(description)

                    package_entry.append(path)

                    self.package_list.append(package_entry)

                    self.all_dependencies[path] = info

                    self.add_dependencies(info.get('dependencies'))

            else:
                print dependencies

    def panel_done(self, picked):

        if 0 > picked < len(self.package_list):
            return

        package = self.package_list[picked]

        package_info = self.all_dependencies[package[len(package) - 1]]

        self.run_with_package(package_info)

    def run_with_package(self, package_info):

        print package_info


class NpmEditCommand(NpmPackageCommand):

    def run_with_package(self, package_info):

        print package_info

        sublime_command_line([package_info.get('path')])


class NpmAddFolderToProjectCommand(NpmPackageCommand):

    def run_with_package(self, package_info):

        sublime_command_line(['-a', package_info.get('path')])


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
