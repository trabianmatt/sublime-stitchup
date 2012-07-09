# Borrows heavily from git.py

import functools
import json
import os
import sublime
import sublime_plugin
import subprocess
import threading


def main_thread(callback, *args, **kwargs):
    # sublime.set_timeout gets used to send things onto the main thread
    # most sublime.[something] calls need to be on the main thread
    sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)


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
            print self.command
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
        print file_name
        if file_name:
            return os.path.dirname(file_name)
        else:
            return self.window.folders()[0]


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

        dependencies = self.package_info.get('dependencies')

        self.all_dependencies = {}

        package_list = []

        for package in dependencies:

            package_entry = [package]

            info = dependencies.get(package)

            package_entry.append(info.get('description'))

            path = info.get('path')

            package_entry.append(path)

            package_list.append(package_entry)

            self.all_dependencies[path] = info

            self.package_list = package_list

        self.window.show_quick_panel(self.package_list, self.panel_done)

    def panel_done(self, picked):

        if 0 > picked < len(self.package_list):
            return

        package = self.package_list[picked]

        package_info = self.all_dependencies[package[2]]

        self.run_with_package(package_info)

    def run_with_package(self, package_info):

        print package_info


class NpmEditCommand(NpmPackageCommand):

    def run_with_package(self, package_info):

        print package_info.get('description')
