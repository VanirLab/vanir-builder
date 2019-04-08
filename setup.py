#! /usr/bin/env python
# vim: set ft=python ts=4 sw=4 sts=4 et :
# -*- coding: utf-8 -*-

# setup.py --- vanir Builder Configuration Utility
#
# Copyright (C) 2019  Chris Pro
#
# License: GPL-2+
# ------------------------------------------------------------------------------
# Install 'dialog' program if it does not yet exist
# ------------------------------------------------------------------------------

# pylint: disable=E1101,W1401

from __future__ import unicode_literals

import argparse
import codecs
import collections
import copy
import locale
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tty
import types
import ConfigParser


#from subprocess import (Popen, STDOUT)
from textwrap import dedent, wrap

# Globals
DIALOG = 'dialog'
GPG_KEY_SERVER = 'pgp.mit.edu'
DEVELOPMENT_MODE = False

# Global file locations
BASE_DIR = os.getcwd()
CONFIG_DIR = 'example-configs'
OVERRIDE_CONF = 'override.conf'
OVERRIDE_DATA = 'override.data'
MASTER_TEMPLATE = 'templates.conf'
BUILDER_CONF = 'builder.conf'
BACKUP_EXTENSION = '.bak'
VANIR_DEVELOPERS_KEYS = 'vanir-developers-keys.asc'
GNUPGHOME = os.path.join(os.path.abspath(BASE_DIR), 'keyrings/git')

# Add 'vanir-builder/libs' directory to sys.path
LIBS_DIR = os.path.join(BASE_DIR, 'libs')
if os.path.exists(LIBS_DIR) and os.path.isdir(LIBS_DIR):
    if LIBS_DIR not in sys.path:
        sys.path.insert(1, LIBS_DIR)

# Import ANSIColor after LIBS_DIR is added to path
from ansi import ANSIColor

locale.setlocale(locale.LC_ALL, '')


def exit(*varargs, **kwargs):  # pylint: disable=W0622
    '''Function to exit.  Maybe restoring some files before exiting.
    '''
    kwargs['title'] = 'System Exit!'
    kwargs['width'] = 80
    kwargs['height'] = 0  # Auto height

    try:
        DefaultUI.ui.infobox(*varargs, **kwargs)
    except AttributeError:
        pass

    # Restore original template.conf
    try:
        config = Config(None)
        if os.path.exists(config.conf_builder + BACKUP_EXTENSION):
            shutil.move(
                config.conf_builder + BACKUP_EXTENSION, config.conf_builder
            )
    except NameError:
        pass

    sys.exit()


def getchar():
    try:
        import termios
    except ImportError:
        import msvcrt
        return msvcrt.getchar()

    def _getchar():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            char = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return char

    return _getchar()


def get_builder_deps():
    '''Install vanir-builder depends if they are not already installed.
    '''
    env = os.environ.copy()
    if not os.path.exists(BUILDER_CONF):
        env['BUILDERCONF'] = MASTER_TEMPLATE

    try:
        env['GET_VAR'] = 'DEPENDENCIES'
        dependencies = subprocess.check_output(
            ['make', '--always-make', '--quiet', 'get-var'],
            env=env
        ).strip()
        env.pop('GET_VAR')
    except subprocess.CalledProcessError:
        print ('\nAn error occurred trying to determine dependencies and therefore setup must now exit')
        print ('Exiting!')
        exit()

    return dependencies.split(' ')


def install_deps(packages=None):
    '''Call vanir-builder make-deps to install packages if they are not already installed.

    The DEPENDENCIES env variable will contain any packages to update.
    '''
    packages = packages or []

    try:
        from subprocess import DEVNULL  # py3k
    except ImportError:
        DEVNULL = open(os.devnull, 'wb')

    ansi = ANSIColor()
    dependencies = set()
    packages += get_builder_deps()

    # Only add packages to dependency list if they are not installed
    for package in packages:
        proc = Popen(['rpm', '-q', '--whatprovides', package], stdout=DEVNULL, stderr=DEVNULL)
        proc.wait()
        if proc.returncode:
            dependencies.add(package)

    if dependencies:
        env = os.environ.copy()
        dependencies = ' '.join(list(dependencies))

        # Prompt and confirm installation of dependencies
        os.system('clear')
        message = 'The following dependencies have not been met:\n'
        print ('{ansi[blue]}{0}{ansi[red]}{1}{ansi[normal]}\r\r'.format(
            message,
            dependencies,
            ansi=ansi))
        print ('\nEnter \'Y\' to install {ansi[red]}ALL{ansi[normal]} dependencies now, or anything else to quit [YyNnQq]: '.format(
            ansi=ansi
        ))
        char = getchar()
        if char.lower() != 'y':
            print ('\nYou selected not to install the dependencies and therefore setup must now exit'.format(
                ansi=ansi
            ))
            print ('Exiting!')
            exit()

        # User confirmed installation of dependencies
        os.system('clear')
        sys.stdout.write(
            'Waiting for {ansi[red]}{0}{ansi[normal]} to install\n'.format(
                dependencies,
                ansi=ansi
            )
        )
        sys.stdout.flush()

        env['DEPENDENCIES'] = dependencies
        proc = Popen(
            ['make', 'install-deps'],
            stdout=DEVNULL,
            stderr=STDOUT,
            env=env
        )
        while proc.poll() is None:
            sys.stdout.write('{ansi[red]}.{ansi[normal]}'.format(ansi=ansi))
            sys.stdout.flush()
            time.sleep(1)
        print

        if proc.returncode:
            print ('\nThere was an error installing dependencies!{ansi[blue]}{ansi[normal]} and therefore setup must now exit'.format(
                ansi=ansi
            ))
            print ('Exiting!')
            exit()


def write_file(filename, text):
    try:
        with codecs.open(filename, 'w', 'utf8') as outfile:
            outfile.write(dedent(text))
    except IOError, err:
        exit(err)


def parse_parentheses(text):
    '''A very simple lexer to parse round parentheses.
    '''
    ansi = ANSIColor()

    lexer = shlex.shlex(text)
    lexer.whitespace = '\t\r\n'

    text = ''
    raw = ''
    count = 0

    for token in lexer:
        chars = token
        if chars[0] in '\'"' and chars[-1] in '\'"':
            new_chars = parse_parentheses(chars[1:-1])
            text += chars[0] + new_chars + chars[-1]
            continue
        if token == '(':
            count += 1
            if raw and raw[-1] == '$':
                chars = '{ansi[blue]}{0}'.format(chars, ansi=ansi)
        elif token == ')':
            if count == 1:
                chars = '{0}{ansi[normal]}'.format(chars, ansi=ansi)
            count -= 1
        elif count:
            if raw and raw[-1] != '(':
                chars = '{ansi[black]}{0}'.format(chars, ansi=ansi)

        raw += token
        text += chars

    return text


def display_configuration(filename):
    '''Display the configuration file.
    '''
    ansi = ANSIColor()
    print '{ansi[bold]}{ansi[black]}{0}:{ansi[normal]}'.format(
        filename,
        ansi=ansi
    )
    try:
        with codecs.open(filename, 'r', 'utf8') as infile:
            for line in infile:
                match = re.match(
                    r'(?P<text>.*?(?=#)|.*)(?P<comment>([#]+.*)|)',
                    line.rstrip()
                )
                if match:
                    line = ''
                    text = match.groupdict()['text']
                    comment = match.groupdict()['comment']
                    if match.groupdict()['text']:
                        var = re.match(r'(?P<var>.*)(?P<text>[?:]?=.*)', text)
                        target = re.match(
                            r'(?P<target>.*[:]+)(?P<text>.*)', text
                        )
                        text = parse_parentheses(text)

                        if var:
                            line += '{ansi[blue]}{d[var]}{ansi[normal]}{d[text]}'.format(
                                d=var.groupdict(),
                                ansi=ansi
                            )
                        elif target:
                            line += '{ansi[red]}{d[target]}{ansi[normal]}{d[text]}'.format(
                                d=target.groupdict(),
                                ansi=ansi
                            )
                        else:
                            line += '{ansi[black]}{0}{ansi[normal]}'.format(
                                text,
                                ansi=ansi
                            )

                    if comment:
                        line += '{ansi[green]}{0}{ansi[normal]}'.format(
                            comment,
                            ansi=ansi
                        )
                print line
    except IOError, err:
        exit(err)


def is_linkable(source, target, replace_file=False, replace_link=False):
    '''Return True if target can be linked to source.
    '''
    # Source does not exist or is a broken link
    if not source or not os.path.exists(source):
        return False

    # Target does not exist or is a broken link
    if target and not os.path.exists(target):
        return True

    # Source and target are same as indicated by device and i-node
    # number
    if os.path.samefile(source, target):
        return False

    # Target is a regular file and 'replace_file' is False
    if not replace_file:
        if os.path.exists(target) and not os.path.islink(target):
            return False

    # Target is a link and 'replace_link' is True
    if replace_link and os.path.islink(target):
        return True

    # Most likely target is a link and 'replace_link' is False
    return False


def soft_link(source, target, replace_file=False, replace_link=False):
    '''Attempt to soft-link a file.  Exit with message on failure.
    '''
    if is_linkable(source, target, replace_file, replace_link):
        try:
            if os.path.lexists(target):
                os.remove(target)
            os.symlink(source, target)
        except OSError, err:
            exit(
                'Error linking:\n{0} to {1}\n\n{2}.'.format(
                    target, source, err.strerror
                )
            )
    else:
        message = 'Unable to link target file to source.'
        exit(
            'Error linking:\n{0} to {1}\n\n{2}'.format(
                target, source, message
            )
        )


class DefaultUI(object):
    '''Default UI contains pointer to selected UI.
    '''
    ui = None

    @classmethod
    def __init__(cls, ui):
        cls.ui = ui


class DialogUI(DefaultUI):
    '''UI Interface to `dialog` API.
    '''
    from dialog import (Dialog, ExecutableNotFound)

    try:
        from textwrap import indent
    except ImportError:

        @staticmethod
        def indent(text, prefix, predicate=None):
            l = []
            for line in text.splitlines(True):
                if (callable(predicate) and predicate(line)) \
                   or (not callable(predicate) and predicate) \
                   or (predicate is None and line.strip()):
                    line = prefix + line
                l.append(line)
            return ''.join(l)

    # Initialize a dialog.Dialog instance
    try:
        dialog = Dialog(dialog=DIALOG)
    except ExecutableNotFound:
        install_deps(['dialog'])
        dialog = Dialog(dialog=DIALOG)

    @classmethod
    def __init__(cls):
        cls.dialog.set_background_title("Vanir Builder Configuration Utility")
        super(DialogUI, cls).__init__(cls)

    @classmethod
    def _auto_height(cls, width, text):
        _max = max(8, 5 + len(wrap(text, width=width)))  # Min of 8 rows
        _min = min(22, _max)  # Max of 22 rows
        return _min

    @classmethod
    def yesno(cls, **info):
        '''YesNo dialog.
        '''
        default = {'colors': True, 'width': 60, 'height': 8, }

        default.update(info)
        code = cls.dialog.yesno(**default)

        if code == cls.dialog.OK:
            return True
        elif code == cls.dialog.CANCEL:
            return False
        elif code == cls.dialog.ESC:
            exit('Escape key pressed. Exiting.')

    @classmethod
    def msgbox(cls, *varargs, **info):
        '''Msgbox dialog.

        Only displays if text is provided. Text can be provided in varargs
        '''
        default = {
            'colors': True,
            'title': 'vanir Setup Information.',
            'width': 72,
            'height': 8,
            'text': ''
        }

        default.update(info)
        if varargs:
            default['text'] = ' '.join(varargs)

        if not default['height']:
            default['height'] = cls._auto_height(
                default['width'], default['text']
            )

        if default['text']:
            cls.dialog.msgbox(**default)

    @classmethod
    def infobox(cls, *varargs, **info):
        '''Infobox dialog.

        Only displays if text is provided. Text can be provided in varargs
        '''
        default = {
            'colors': True,
            'title': 'vanir Setup Information.',
            'width': 72,
            'height': 8,
            'text': ''
        }

        default.update(info)
        if varargs:
            default['text'] = ' '.join(varargs)

        if not default['height']:
            default['height'] = cls._auto_height(
                default['width'], default['text']
            )

        if default['text']:
            cls.dialog.infobox(**default)

    @classmethod
    def list_done(cls, code, tag, helper=None):
        if not helper:
            helper = {}
        no_help = "You asked for help about something called '{0}'. Sorry, but I am quite incompetent in this matter."

        if code == 'help':
            cls.msgbox(
                helper.get(tag[0], no_help.format(tag[0])),
                height=0,
                width=60
            )
            return False

        elif code == cls.dialog.CANCEL:
            exit('User aborted setup.')

        elif code == cls.dialog.ESC:
            exit('User aborted setup.')

        else:
            return True

    @classmethod
    def checklist(cls, **info):
        '''Checklist dialog.
        '''
        default = {
            'colors': True,
            'height': 0,
            'width': 0,
            'list_height': 0,
            'choices': [],
            'title': '',
            'help_button': False,
            'item_help': False,
            'help_tags': False,
            'help_status': False,
            'text': '',
        }
        default.update(info)
        helper = default.pop('helper', {})

        while True:
            code, tag = cls.dialog.checklist(**default)
            if cls.list_done(code, tag, helper):
                break

        return tag

    @classmethod
    def radiolist(cls, **info):
        '''Radiolist dialog.
        '''
        default = {
            'colors': True,
            'height': 0,
            'width': 0,
            'list_height': 0,
            'choices': [],
            'title': '',
            'help_button': False,
            'item_help': False,
            'help_tags': False,
            'help_status': False,
            'text': '',
        }
        default.update(info)
        helper = default.pop('helper', {})

        while True:
            code, tag = cls.dialog.radiolist(**default)
            if cls.list_done(code, tag, helper):
                break

        return tag

    @classmethod
    def release(cls, **info):
        '''Display `select release` dialog of vanir release version to build.
        '''
        return cls.radiolist(**info)

    @classmethod
    def override(cls, **info):
        '''Display use override confirmation.
        '''
        return cls.yesno(**info)

    @classmethod
    def repo(cls, **info):
        '''Display `choose repo` dialog.
        '''
        return cls.radiolist(**info)

    @classmethod
    def ssh_access(cls, **info):
        '''Display ssh-access dialog.
        '''
        return cls.yesno(**info)

    @classmethod
    def template_only(cls, **info):
        '''Display dialog choice of building only templates.
        '''
        return cls.yesno(**info)

    @classmethod
    def dists(cls, **info):
        '''Display DISTS_VM's for selection.
        '''
        return cls.checklist(**info)

    @classmethod
    def builders(cls, **info):
        '''Display BUILDER_PLUGINS's for selection.
        '''
        return cls.checklist(**info)

    @classmethod
    def verify_keys(cls, **info):
        '''Display `verify keys` confirmation dialog.
        '''
        default = {'height': 12, }
        default.update(info)
        return cls.yesno(**default)

    @classmethod
    def get_sources(cls, **info):
        '''Display get-sources dialog.
        '''
        result = cls.yesno(**info)
        get_sources = 1 if result else 0

        # Download sources
        if get_sources:
            try:
                # py3k
                from subprocess import DEVNULL  # pylint: disable=W0404
            except ImportError:
                DEVNULL = open(os.devnull, 'wb')

            env = os.environ.copy()
            env['bold'] = ''
            env['normal'] = ''
            env['black'] = ''
            env['red'] = ''
            env['green'] = ''
            env['blue'] = ''
            env['white'] = ''

            args = ['make', 'get-sources']
            p = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=DEVNULL,
                close_fds=True,
                env=env
            )

            default = {
                #'colors': True,
                #'scrollbar': True,
                'height': 40,
                'width': 120,
            }

            cls.dialog.programbox(
                fd=p.stdout.fileno(),
                text="Get sources",
                **default
            )
            retcode = p.wait()

            # Context manager support for subprocess.Popen objects requires
            # Python 3.2 or later.
            p.stdout.close()
            return retcode


class Config(object):
    '''Configuration objects holds all config data.

    Provides provides methods to read and write the data
    '''
    MARKER = object()

    _makefile_vars = {
        'about': '',
        'release': '',
        'ssh_access': 0,
        'template_only': 0,
        'git_baseurl': '',
        'git_prefix': '',
        'git_prefix_default': '',
        'use_vanir_repo_version': '',
        'use_vanir_repo_testing': '',
        'dist_dom0_selected': '',
        'dists_vm_all': [],
        'dists_vm_selected': [],
        'builders_selected': [],
        'template_aliases_reversed': [],
        'template_labels': [],
        'template_labels_reversed': [],
    }

    _defaults_builder = {
        'id': '',
        'type': '',
        'description': '',
        'optional': [],
        'require': [],
        'require_in': [],
        'development': False,
    }

    _defaults_key = {
        'id': '',
        'type': '',
        'key': '',
        'owner': '',
        'fingerprint': None,
        'verify': '',
        'url': '',
    }

    _defaults_repo = {'type': '', 'description': '', 'prefix': '', }

    def __init__(self, filename, **options):
        '''Init.

        filename is the name of the main configuration file to load which
        is typically .salt.conf and is configurable with command-line option
        '-c'
        '''
        self.filename = filename
        self.options = options

        self.dir_builder = self.options.get('dir_builder') or os.path.abspath(
            os.path.curdir
        )
        self.dir_configurations = os.path.join(self.dir_builder, CONFIG_DIR)

        # Override configuration filename will override and merge into .setup.data
        self.conf_override_data = os.path.join(self.dir_builder, OVERRIDE_DATA)

        self.parser = ConfigParser.ConfigParser(
            dict_type=collections.OrderedDict
        )
        self.parser.add_section('makefile')
        self.sections = []
        self.releases = collections.OrderedDict()
        self.keys = collections.OrderedDict()
        self.repos = collections.OrderedDict()
        self.builders = collections.OrderedDict()

        self._init_makefile_vars()

        self.conf_template = os.path.join(
            self.dir_configurations, MASTER_TEMPLATE
        )
        self.conf_override = os.path.join(self.dir_builder, OVERRIDE_CONF)
        self.conf_builder = os.path.join(self.dir_builder, BUILDER_CONF)

        # Copy example-configs/template.conf to builder.conf if
        # the configuration file does not yet exist
        self._create_builder_conf(force=False)

        # Parse Makefiles
        self._parse_makefiles()

        # Set up any branch specific override configurations
        self._overrides()

        # Load .setup.data
        if filename and os.path.exists(filename):
            self._load()
            if os.path.exists(self.conf_override_data):
                self._load(self.conf_override_data)

    def _init_makefile_vars(self):
        for key, value in self._makefile_vars.items():
            setattr(self, key, value)

    def _create_builder_conf(self, force=False):
        '''Copies example-configs/template.conf to builder.conf
        '''
        if not os.path.exists(self.conf_builder) or force:
            try:
                if os.path.exists(self.conf_builder) and force:
                    os.remove(self.conf_builder)

                shutil.copy2(self.conf_template, self.conf_builder)

                # ABOUT
                replace = ReplaceInplace(self.conf_builder)
                replace.add(
                    **{
                        'replace': r'@echo "{0}"'.format(MASTER_TEMPLATE),
                        'text': r'@echo "{0}"'.format(BUILDER_CONF),
                    }
                )
                replace.start()
            except IOError, err:
                exit(err)

    #def __getattribute__(self, name):
    #    return super(Config, self).__getattribute__(name)

    def _coerce_value(self, default, value):
        if type(value) != type(default):
            try:
                if isinstance(default, types.BooleanType):
                    value = bool(value)
                elif isinstance(default, types.IntType):
                    value = int(value)
                elif isinstance(default, types.FloatType):
                    value = float(value)
                elif isinstance(default, types.ListType):
                    if isinstance(value, types.StringTypes):
                        if value.strip().lower() in ['none', 'null']:
                            value = []
                        else:
                            value = value.strip().split()
                elif isinstance(default, types.NoneType):
                    value = None
            except ValueError:
                value = default
        return value

    def _coerce_values(self, defaults, values):
        if not isinstance(defaults, collections.Mapping):
            return values
        if isinstance(values, collections.Mapping):
            for key, value in values.items():
                if key in defaults:
                    values[key] = self._coerce_value(defaults[key], value)
        return values

    def __setattr__(self, name, value):
        if name in self._makefile_vars:
            default = self._makefile_vars[name]
            value = self._coerce_value(default, value)
            self.parser.set('makefile', name, value)
        return super(Config, self).__setattr__(name, value)

    def _get_section(self, section_name):
        adict = collections.OrderedDict()
        options = self.parser.options(section_name)
        for option in options:
            try:
                adict[option] = self.parser.get(section_name, option)
                #if adict[option] == -1:
                #    adict.pop(option, None)
            except (ConfigParser.Error, TypeError):
                adict[option] = None
        return adict

    def _load(self, filename=None):
        if not filename:
            filename = self.filename

        self.parser.readfp(codecs.open(filename, 'r', 'utf8'))
        for section_name in self.parser.sections():
            section = self._get_section(section_name)
            if not section:
                continue
            section_type = section.get('type', section_name)
            if section_type == 'gpg':
                config = copy.deepcopy(self._defaults_key)
                section['id'] = section_name
                config.update(section)
                self.keys[section_name] = config
            elif section_type == 'repo':
                config = copy.deepcopy(self._defaults_repo)
                config.update(section)
                self.repos[section_name] = config
            elif section_type == 'builder':
                config = copy.deepcopy(self._defaults_builder)
                config.update(section)
                self.builders[section_name] = self._coerce_values(
                    self._defaults_builder, config
                )
            elif section_type == 'releases':
                self.releases = section

    def _overrides(self):
        '''Set up any branch specific override configurations.
        '''
        #--------------------------------------------------------------------------
        # See if a branch specific override configuration file exists
        #--------------------------------------------------------------------------
        branch = sh.git('rev-parse', '--abbrev-ref', 'HEAD').strip()
        override_path = None

        # Skip if overrides already exists and is a regular file
        if not (
            os.path.exists(self.conf_override) and
            not os.path.islink(self.conf_override)
        ):
            directory = self.dir_configurations
            override = os.path.basename(self.conf_override)

            patterns = []
            # Example: example-configs/r3-feature_branch-override.conf
            #          example-configs/r3-master-override.conf
            patterns.append(
                '{0}/r{1}-{2}-{3}'.format(
                    directory, self.release, branch, override
                )
            )

            # Example: example-configs/feature_branch-override.conf
            #          example-configs/master-override.conf
            patterns.append('{0}/{1}-{2}'.format(directory, branch, override))

            # Example: example-configs/override.conf
            patterns.append('{0}/{1}'.format(directory, override))

            for pattern in patterns:
                if os.path.exists(pattern):
                    override_path = pattern
                    break

            if is_linkable(
                override_path,
                self.conf_override,
                replace_link=True
            ):
                info = {
                    'title':
                    'Use Branch Specific Override Configuration File?',
                    'default_button': 'yes',
                    'text': dedent(
                        '''\
                    A branch specific configuration file was found in your personal directory:
                    {0}.

                    Would you like to use and override the other provided repos?
                    '''.format(override_path)
                    ),
                }

                # Link if user confirmed override
                if DefaultUI.ui.override(**info):
                    soft_link(
                        override_path,
                        self.conf_override,
                        replace_link=True
                    )

                    # Re-parse Makefiles
                    self._parse_makefiles()

    def _parse_makefiles(self):
        '''
        '''
        from sh import make  # pylint: disable=E0611
        env = os.environ.copy()
        make = make.bake(
            '--always-make',
            '--quiet',
            'get-var',
            directory=self.dir_builder,
            _env=env
        )

        # Get variables from Makefile
        try:
            env['GET_VAR'] = 'RELEASE'
            self.release = make().strip()

            env['GET_VAR'] = 'SSH_ACCESS'
            self.ssh_access = make().strip()

            env['GET_VAR'] = 'TEMPLATE_ONLY'
            self.template_only = make().strip()

            env['GET_VAR'] = 'BUILDER_PLUGINS_ALL'
            self.builders_selected = make().strip()

            env['GET_VAR'] = 'GIT_BASEURL'
            self.git_baseurl = make().strip()

            env['GET_VAR'] = 'GIT_PREFIX'
            self.git_prefix = make().strip()
            self.git_prefix_default = self.git_prefix

            env['GET_VAR'] = 'USE_VANIR_REPO_VERSION'
            self.use_vanir_repo_version = make().strip()

            env['GET_VAR'] = 'USE_VANIR_REPO_TESTING'
            self.use_vanir_repo_testing = make().strip()

            env['GET_VAR'] = 'DISTS_VM'
            self.dists_vm_selected = make().strip().split()

            env['GET_VAR'] = 'DIST_DOM0'
            self.dist_dom0_selected = make().strip().split()

            env['SETUP_MODE'] = '1'
            env['GET_VAR'] = 'DISTS_VM'
            self.dists_vm_all = make().strip().split()

            env['GET_VAR'] = 'TEMPLATE_ALIAS'
            aliases = make().strip().split()
            self.template_aliases = dict(
                [
                    (item.split(':')) for item in aliases
                ]
            )
            self.template_aliases_reversed = dict(
                [
                    (
                        value, key
                    ) for key, value in self.template_aliases.items()
                ]
            )

            env['GET_VAR'] = 'TEMPLATE_LABEL'
            labels = make().strip().split()
            self.template_labels = dict([(item.split(':')) for item in labels])
            self.template_labels_reversed = dict(
                [
                    (
                        value, key
                    ) for key, value in self.template_labels.items()
                ]
            )

            self.about = sh.make(
                '--always-make',
                '--quiet',
                'about',
                directory=self.dir_builder
            )
        except sh.ErrorReturnCode:
            pass

    def write_configuration(self):
        '''Write builder.conf configuration.
        '''
        replace = ReplaceInplace(self.conf_builder)
        dists_vm = ''

        ### -- INFO -----------------------------------------------------------
        # Format about
        info = '''\
            ################################################################################
            #
            # vanir Release: {vars[release]}
            # Source Prefix: {vars[git_prefix]} (repo)
            #
            # Master Configuration File(s):
            # {about}
            #
            # builder.conf copied from:
            # {vars[conf_template]}
            #
            ################################################################################
            '''.format(
            about=' '.join(self.about.split()),
            vars=vars(self)
        )

        ### -- DISTS_VM -------------------------------------------------------
        for dist in self.dists_vm_selected:
            dists_vm += 'DISTS_VM += {0}\n{1}'.format(dist, '              ')
        dists_vm = dists_vm.strip()

        dists = '''\
            ifneq "$(SETUP_MODE)" "1"

              # Enabled DISTS_VMs
              DISTS_VM :=
              {dists_vm}

            endif
            '''.format(
            dists_vm=dists_vm
        )

        ### -- BUILDER_PLUGINS ------------------------------------------------
        plugins = ''
        for plugin in self.builders_selected:
            plugins += 'BUILDER_PLUGINS += {0}\n{1}'.format(
                plugin, '              '
            )
        plugins = plugins.strip()

        plugins = '''\

              # Enabled BUILDER_PLUGINS
              BUILDER_PLUGINS :=
              {plugins}
            '''.format(
            plugins=plugins
        )

        # INFO
        replace.add(
            **{
                'insert_after': r'.*[[]=setup info start=[]]',
                'insert_until': r'.*[[]=setup info stop=[]]',
                'text': dedent(info).rstrip('\n'),
            }
        )

        # DISTS_VM
        replace.add(
            **{
                'insert_after': r'.*[[]=setup dists start=[]]',
                'insert_until': r'.*[[]=setup dists stop=[]]',
                'text': dedent(dists).rstrip('\n'),
            }
        )

        # BUILDER_PLUGINS
        replace.add(
            **{
                'insert_after': r'.*[[]=setup plugins start=[]]',
                'insert_until': r'.*[[]=setup plugins stop=[]]',
                'text': dedent(plugins),
            }
        )

        # RELEASE
        replace.add(
            **{
                'replace': r'RELEASE[ ]*[?:]?=[ ]*[\d.]+',
                'text': r'RELEASE := {0}'.format(self.release),
            }
        )

        # SSH_ACCESS
        replace.add(
            **{
                'replace': r'SSH_ACCESS[ ]*[?:]?=[ ]*[\d]',
                'text': r'SSH_ACCESS := {0}'.format(self.ssh_access),
            }
        )

        # GIT_BASEURL
        replace.add(
            **{
                'replace': r'GIT_BASEURL[ ]*[?:]?=[ ]*.*',
                'text': r'GIT_BASEURL := {0}'.format(self.git_baseurl),
            }
        )

        # GIT_PREFIX
        replace.add(
            **{
                'replace': r'GIT_PREFIX[ ]*[?:]?=[ ]*.*',
                'text': r'GIT_PREFIX := {0}'.format(self.git_prefix),
            }
        )

        # TEMPLATE_ONLY
        replace.add(
            **{
                'replace': r'TEMPLATE_ONLY[ ]*[?:]?=[ ]*.*',
                'text': r'TEMPLATE_ONLY ?= {0}'.format(self.template_only),
            }
        )

        # VANIR_REPOSITORIES
        replace.add(
            **{
                'replace': r'^.*USE_VANIR_REPO_TESTING[ ]*[?:]?=[ ]*[\d]',
                'text': r'USE_VANIR_REPO_TESTING = {0}'.format(self.use_vanir_repo_testing),
            }
        )
        if self.use_vanir_repo_testing == "1":
              self.use_vanir_repo_version = self.release

        if self.use_vanir_repo_version == self.release:
            use_vanir_repo_version = r'USE_VANIR_REPO_VERSION = $(RELEASE)'
        else:
            use_vanir_repo_version = r'# USE_VANIR_REPO_VERSION = $(RELEASE)'

        replace.add(
            **{
                'replace': r'^.*USE_VANIR_REPO_VERSION[ ]+[?]?[=].*$',
                'text': use_vanir_repo_version,
            }
        )

        # INCLUDE_OVERRIDE_CONF
        if os.path.exists(self.conf_override):
            override = r'INCLUDE_OVERRIDE_CONF ?= true'
        else:
            override = r'#INCLUDE_OVERRIDE_CONF ?= true'
        replace.add(
            **{
                'replace': r'^.*INCLUDE_OVERRIDE_CONF[ ]+[?]?[=].*$',
                'text': r'{0}'.format(override),
            }
        )

        # Start the search and replace process on the configuration file
        replace.start()

    def display_configuration(self):
        ansi = ANSIColor()
        display_configuration(self.conf_builder)
        info = '\nNew configuration file written to: {0}\n'.format(
            self.conf_builder
        )

        install_vanir = '''
            Complete vanir Build Steps
            --------------------------
            make install-deps
            make get-sources
            make vanir
            make iso
            '''

        install_vanir_vm = '''
            Template Only Build Steps
            -------------------------
            make install-deps
            make get-sources
            make vanir-vm
            make template
            '''

        if self.template_only:
            info += dedent(install_vanir_vm)
        else:
            info += dedent(install_vanir)
        print '{ansi[green]}{0}{ansi[normal]}'.format(info, ansi=ansi)


class Wizard(Config):
    ''''''

    def __init__(self, ui, **kwargs):
        self.ui = ui
        DefaultUI.ui = ui
        self.cli_args = kwargs
        super(Wizard, self).__init__(kwargs['config_filename'], **kwargs)

    def __call__(self):
        ## Check / Install Keys
        ## set force value to 'force' to force re-download and verify
        self.verify_keys(self.keys, force=False)

        ## Choose release version
        ## Soft link 'examples/templates.conf' to 'builder.conf'
        self.set_release()

        ## Prompt for selection of base repo to use for build
        self.set_repo()

        ## Select which vanir packages repositories to use for partial builds
        self.set_vanir_repos()

        ## Choose if user has git ssh (commit) or http access to private repos
        if os.path.exists(self.conf_override):
            self.set_ssh_access()

        ## Choose to build a complete system or templates only
        self.set_template_only()

        ## Select which templates to build (DISTS_VM)
        self.set_dists()

        ## Enable builders
        self.set_builders()

        ## Write builder.conf
        self.write_configuration()

        ## Display builder.conf
        self.display_configuration()

    def check_gnupghome(self, gnupghome):
        if not os.path.exists(gnupghome):
            os.makedirs(gnupghome, mode=0700)

    def gpg_verify_key(self, key_data):
        verified = False
        env = os.environ.copy()
        env['GNUPGHOME'] = GNUPGHOME
        self.check_gnupghome(GNUPGHOME)

        try:
            text = sh.gpg(
                '--with-colons',
                '--fingerprint',
                key_data['key'],
                _env=env
            ).strip()
        except sh.ErrorReturnCode:
            return False

        for fingerprint in text.split('\n'):
            if fingerprint.startswith(u'fpr:') and fingerprint == key_data[
                'verify'
            ]:
                verified = True
                break

        if not verified:
            print sh.gpg('--fingerprint', key_data['key'], _env=env)
            return False

        return verified

    def verify_keys(self, keys, message=None, force=False):
        env = os.environ.copy()
        env['GNUPGHOME'] = GNUPGHOME
        self.check_gnupghome(GNUPGHOME)

        for key_id, key_data in keys.items():
            key = key_data['key']
            is_key_missing = True
            try:
                text = sh.gpg('--list-key', key, _env=env)
                is_key_missing = text.exit_code
            except sh.ErrorReturnCode, err:
                # exit_code will be non-zero and will trigger installation and verification of keys
                pass

            if force or is_key_missing:
                info = {
                    'title': 'Add Key {0}'.format(key_id),
                    'default_button': 'no',
                }
                if message:
                    info[
                        'text'
                    ] = u'Owner: {key_data[owner]}\n\n{0}\n\nSelect "Yes" to add or "No" to exit'.format(
                        message,
                        key_data=key_data
                    )
                elif force:
                    info[
                        'text'
                    ] = u'Owner: {key_data[owner]} forced get.\n\nSelect "Yes" to re-add or "No" to exit'.format(
                        key_data=key_data
                    )
                else:
                    info[
                        'text'
                    ] = u'Owner: {key_data[owner]} key does not exist.\n\nSelect "Yes" to add or "No" to exit'.format(
                        key_data=key_data
                    )

                if not self.ui.verify_keys(**info):
                    exit(
                        'User aborted setup: Exiting setup since keys can not be installed'
                    )

                # Receive key from keyserver
                else:
                    try:
                        text = sh.gpg(
                            '--keyserver',
                            GPG_KEY_SERVER,
                            '--recv-keys',
                            key,
                            _env=env
                        )
                        sh.gpg(
                            sh.echo('{0}:6:'.format(key)),
                            '--import-ownertrust',
                            _env=env
                        )
                    except sh.ErrorReturnCode, err:
                        print err.message
                        exit(err.message)

            # Verify key on every run
            result = self.gpg_verify_key(key_data)
            if not result:
                exit(
                    {
                        'title':
                        '{key_data[owner]} fingerprint failed!'.format(
                            key_data=key_data
                        ),
                        'text':
                        '\nWrong fingerprint\n{key_data[fingerprint]}\n\nExiting!'.format(
                            key_data=key_data
                        ),
                    }
                )

        # Add developers keys
        try:
            sh.gpg('--import', VANIR_DEVELOPERS_KEYS, _env=env)
        except sh.ErrorReturnCode, err:
            exit(
                'Unable to import vanir developer keys: {0}. Please install them manually.\n{1}'.format(
                    VANIR_DEVELOPERS_KEYS, err
                )
            )

        return True

    def set_release(self):
        '''Select release version of vanir to build.
        '''
        choices = []
        default = self.release or self.releases.pop('default')

        for release, description in self.releases.items():
            if release in ['default']:
                continue
            selected = str(release) == str(default)
            choices.append((release, description, selected))

        info = {
            'title': 'Choose Which vanir Release To Use To Build Packages',
            'choices': choices,
            'width': 76,
            'height': 16,
        }

        self.release = str(self.ui.release(**info))  # pylint: disable=W0201

    def set_repo(self):
        '''Set source repo prefix.
        '''
        choices = []
        default_set = False
        full_prefix = '{0}/{1}'.format(self.git_baseurl, self.git_prefix)

        for repo in self.repos.values():
            toggle = full_prefix.endswith(repo['prefix'])
            if toggle:
                default_set = True
            choices.append((repo['prefix'], repo['description'], toggle))

        choices.insert(
            0, (
                self.git_prefix_default, 'Stable - Default Repo',
                not default_set
            )
        )

        info = {
            'title': 'Choose Source Repos To Use To Build Packages',
            'choices': choices,
            'width': 76,
            'height': 16,
        }

        self.git_prefix = self.ui.repo(**info)  # pylint: disable=W0201

    def set_ssh_access(self):
        '''Set GIT_BASEURL and GIT_PREFIX to allow ssh (write) access to repo.
         Convert:
           `GIT_BASEURL` from `git://github.com` to `git@github.com:repo`
         - and -
           `GIT_PREFIX` from `repo/vanir-` to `vanir-`
        '''
        default_button = 'yes' if self.ssh_access else 'no'
        info = {
            'title': 'Enable SSH Access',
            'default_button': default_button,
            'text': dedent(
                '''\
                Do you have ssh access to the repos?

                Select 'Yes' to configure urls to match git or 'No' for https"
            '''
            ),
        }
        result = self.ui.ssh_access(**info)
        ssh_access = 1 if result else 0

        if ssh_access:
            if '/' in self.git_prefix:
                repo, prefix = self.git_prefix.split('/')
                self.git_prefix = prefix  # pylint: disable=W0201
            else:
                repo = self.git_baseurl.split(':')[-1]
                prefix = self.git_prefix

        # Re-write baseurl depending on ssh_access mode
        baseurl = re.match(
            r'^(.*//|.*@)(.*(?=[:])|.*)([:].*|)', self.git_baseurl
        )
        if ssh_access:
            self.git_baseurl = 'git@{0}:{1}'.format(
                baseurl.group(2), repo
            )  # pylint: disable=W0201
        else:
            self.git_baseurl = 'https://{0}'.format(
                baseurl.group(2)
            )  # pylint: disable=W0201

        self.ssh_access = ssh_access  # pylint: disable=W0201

    def set_template_only(self):
        '''Choose to build a complete system or templates only.
        '''
        default_button = 'yes' if self.template_only else 'no'
        info = {
            'title': 'Build Template Only?',
            'default_button': default_button,
            'text': dedent(
                '''\
                Would you like to build only the templates?

                Select 'Yes' to to only build templates or 'No' for complete build
            '''
            ),
        }
        self.template_only = self.ui.template_only(
            **info
        )  # pylint: disable=W0201

    def set_dists(self):
        ''''''
        choices = []
        helper = {}
        for dist in self.dists_vm_all:
            alias = self.template_aliases.get(dist, '')
            aliasr = self.template_aliases_reversed.get(dist, '')
            label = self.template_labels.get(alias or dist, '')

            tag = aliasr or dist
            item = label
            help_text = dist if dist != tag else ''

            helper[tag] = dedent(
                '''\
                \Zb\Z4Distribution:\Zn {0}
                \Zb\Z4Template Label:\Zn {1}
                \Zb\Z4Template Alias:\Zn {2}
            '''
            ).format(tag, item, help_text)

            if help_text:
                help_text = 'Alias value: {0}'.format(help_text)

            choices.append(
                (
                    tag, item, dist in self.dists_vm_selected, help_text
                )
            )

        info = {
            'helper': helper,
            'height': 0,
            'width': 0,
            'list_height': 0,
            'choices': choices,
            'title': 'Template Distribution Selection',
            'help_button': True,
            'item_help': True,
            'help_tags': True,
            'help_status': True,
            'text': dedent(
                '''\
                \Zb\Z4Left column contains DIST name\Zn
                \Zb\Z4Right column contains TEMPLATE_LABEL\Zn
            '''
            ),
        }

        self.dists_vm_selected = self.ui.dists(**info)  # pylint: disable=W0201

    def set_vanir_repos(self):
        ''''''
        choices = []
        default_stable = False
        default_testing = False

        if self.use_vanir_repo_testing == "1":
            default_testing = True
            self.use_vanir_repo_version = self.release

        if self.use_vanir_repo_version == self.release:
            default_stable = True

        choices.insert(0, ('current', 'Stable repository', default_stable))
        choices.insert(1, ('current-testing', 'Testing repository', default_testing))

        info = {
            'title': 'Choose Pre-Built Packages Repositories',
            'choices': choices,
            'width': 76,
            'height': 10,
        }

        vanir_repos_selected = self.ui.dists(**info)  # pylint: disable=W0201
        if 'current' in vanir_repos_selected:
            self.use_vanir_repo_version = self.release
        else:
            self.use_vanir_repo_version = ''

        if 'current-testing' in vanir_repos_selected:
            self.use_vanir_repo_testing = "1"
        else:
            self.use_vanir_repo_testing = "0"

    def get_sources(self):
        '''Prompt user to get sources.
        '''
        info = {
            'title': 'Get sources',
            'default_button': 'yes',
            'height': 0,
            'width': 0,
            'text': dedent(
                '''\
                Either a BUILDER_PLUGIN has been added or vanir sources have not
                yet been downloaded.

                Would you like to get vanir source files now? If you choose no you
                may need to run set again after getting sources manually to be able
                to select some VMs for building.

                Select 'Yes' to download and merge sources or 'No' to skip"
            '''
            ),
        }
        self.ui.get_sources(**info)

    def set_builders(self):
        ''''''

        # Build required depends list
        def _depends(builder, key):
            depends = []
            if not builder.get(key, None):
                return depends
            items = builder[key]
            # Filter builder depends to only dists_vm_selected
            for item in items:  # dist in dists from require_in
                for dist in self.dists_vm_selected + \
                        (['dom0'] if not self.template_only else []):
                    alias = self.template_aliases.get(dist, dist)
                    if item in alias:
                        if dist not in depends:
                            depends.append(dist)
            return depends

        def _missing():
            missing = {}
            for builder in self.builders.values():
                # Check to see if a disabled builder has dist vms selected and warn
                if builder['id'] not in self.builders_selected:
                    for dist in self.dists_vm_selected + \
                            (['dom0'] if not self.template_only else []):
                        alias = self.template_aliases.get(dist, dist)
                        for item in builder['require_in']:
                            if item in alias:
                                missing.setdefault(builder['id'], [])
                                if dist not in missing[builder['id']]:
                                    missing[builder['id']].append(dist)
            return missing

        def _requires():
            requires = {}
            for builder_name in self.builders_selected:
                builder = self.builders.get(builder_name, {})
                for plugin in builder.get('require', []):
                    if plugin not in self.builders_selected:
                        requires.setdefault(builder_name, [])
                        requires[builder_name].append(plugin)
            return requires

        def _requires_key():
            for builder_name in self.builders_selected:
                builder = self.builders.get(builder_name, {})
                if builder.get('key', False):
                    # Setup will exit if user chooses not to install key
                    message = 'The BUILDER_PLUGIN {0} requires a third party key.'.format(
                        builder['id']
                    )
                    key_id = '0x{0}'.format(builder['key'][-8:])
                    self.verify_keys({key_id: builder}, message=message)
            return True

        def _colorize(items, missing):
            colorized = []
            for item in items:
                if item in missing:
                    colorized.append('\Z1{0}\Zn'.format(item))
                else:
                    colorized.append('\Z2{0}\Zn'.format(item))
            return colorized

        while True:
            choices = []
            helper = {}
            missing = _missing()
            requires = _requires()

            for builder in self.builders.values():
                # Skip development plugins if development mode was not enabled (--development)
                if builder.get('development', None) and not self.cli_args.get(
                    'development', None
                ):
                    continue

                tag = builder['id']
                help_text = builder['description']

                helper_text = dedent(
                    '''\
                    \Zb\Z4Builder Plugin:\Zn {0}
                    \Zb\Z4Description:\Zn {1}
                '''
                ).format(tag, help_text)

                require = []
                for builder_name in builder['require']:
                    if builder_name in self.builders_selected:
                        require.append('\Z2{0}\Zn'.format(builder_name))
                    else:
                        require.append('\Z1{0}\Zn'.format(builder_name))

                if require:
                    helper_text += '\Zb\Z4This plugin requires: {0}\n'.format(
                        ' '.join(require)
                    )
                    require = 'Requires: {0}'.format(' '.join(require))
                else:
                    helper_text += '\Zb\Z4This plugin requires:\Zn None\n'

                require_in = _colorize(
                    _depends(builder, 'require_in'), missing.get(
                        tag, []
                    )
                ) or None
                if require_in:
                    helper_text += '\Zb\Z4This plugin is needed by:\Zn {0}\n'.format(
                        ' '.join(require_in)
                    )
                    require_in = 'For: {0}'.format(' '.join(require_in))
                else:
                    helper_text += '\Zb\Z4This plugin is needed by:\Zn None\n'

                optional = _depends(builder, 'optional') or None
                if optional:
                    helper_text += '\Zb\Z4Optional plugin for:\Zn {0}\n'.format(
                        ' '.join(optional)
                    )
                    optional = 'For: {0}'.format(' '.join(optional))

                item = require or require_in or optional or ''
                helper[tag] = helper_text
                choices.append(
                    (
                        tag, item, builder['id'] in self.builders_selected,
                        help_text
                    )
                )

            info = {
                'helper': helper,
                'height': 0,
                'width': 0,
                'list_height': 0,
                'choices': choices,
                'title': 'Builder Plugins Selection',
                'help_button': True,
                'item_help': True,
                'help_tags': True,
                'help_status': True,
                'text': dedent(
                    '''\
                    Select from the following list any builder plugins to be enabled.

                    Note that some plugins are required to build specific VM's as will
                    be indicated by the comment to the left of the plugin choice.
                '''
                ),
            }

            builders_selected = self.builders_selected
            self.builders_selected = self.ui.builders(
                **info
            )  # pylint: disable=W0201

            # Selected builders changed; write and reload config file to reflect
            # changes
            if builders_selected != self.builders_selected:
                # Check if BUILDER_PLUGIN requires a key to install; prompt to install
                # Setup will exit if user chooses not to install key
                _requires_key()

                self.write_configuration()
                self._parse_makefiles()

                # Download sources
                # TODO: determine if BUILDER_PLUGIN has previously been downloaded
                self.get_sources()
                self._parse_makefiles()

            missing = _missing()
            requires = _requires()
            if requires:
                text = ''
                for builder_name, missing_builder in requires.items():
                    text += '\Z1{0}\Zn is selected to be installed but\n'.format(
                        builder_name
                    )
                    text += '\Z4{0}\Zn is not enabled! Either enable \Z4{0}\Zn or disable \Z1{1}\Zn.\n\n'.format(
                        ' '.join(missing_builder), builder_name
                    )
                self.ui.msgbox(text)
            elif missing:
                text = ''
                for builder_name, missing_vms in missing.items():
                    text += '\Z1{0}\Zn are selected to be installed but\n'.format(
                        ' '.join(missing_vms)
                    )
                    text += '\Z4{0}\Zn is not enabled! Either enable \Z4{0}\Zn or exit to re-pick VMs.\n\n'.format(
                        builder_name
                    )
                self.ui.msgbox(text)
            else:
                break


class ReplaceInplace(object):
    def __init__(self, filename):
        self.filename = filename
        self.rules = {}

    defaults = {
        # key to use to match line
        'match_key': None,

        # text will be inserted below pattern matched line. Keeps pattern.
        'insert_after': None,

        # all text before this line will be removed.  Keeps pattern
        # if value is `None`, stop insert mode after initial insert
        'insert_until': None,
        'replace': None,
        'text': None,
        'find': None,
        'start_line': None,
        'stop_line': None,
    }

    def add(self, **kwargs):
        default = copy.deepcopy(self.defaults)
        default.update(kwargs)

        if default['insert_after']:
            default['insert_after'] = re.compile(
                r'{0}'.format(
                    default[
                        'insert_after'
                    ]
                )
            )
            default['match_key'] = 'insert_after'

            if default['insert_until']:
                default['insert_until'] = re.compile(
                    r'{0}'.format(
                        default[
                            'insert_until'
                        ]
                    )
                )

        elif default['replace']:
            default['replace'] = re.compile(r'{0}'.format(default['replace']))
            default['match_key'] = 'replace'

        match_key = default[default['match_key']]
        self.rules[match_key] = default

    def start(self):
        import fileinput
        insert_mode = False
        stop = []

        for line in fileinput.input(
            self.filename,
            inplace=True,
            backup=BACKUP_EXTENSION
        ):
            line = line.rstrip('\n')
            for rule in self.rules:
                if rule.search(line):
                    if self.rules[rule]['match_key'] == 'insert_after':
                        insert_mode = True
                        stop.append(self.rules[rule]['insert_until'])
                        print line
                        print self.rules[rule]['text']
                    elif self.rules[rule]['match_key'] == 'replace':
                        line = rule.sub(self.rules[rule]['text'], line)

            for rule in stop:
                if re.match(rule, line):
                    stop.remove(rule)
                    insert_mode = False

            if not insert_mode:
                print line


def set_default_subparser(self, name, args=None):
    """Default Subparser Selection.

    Call after setup, just before parse_args()
    name: is the name of the subparser to call by default
    args: if set is the argument list handed to parse_args()

    Tested with 2.7, 3.2, 3.3, 3.4
    it works with 2.6 assuming argparse is installed

    http://stackoverflow.com/questions/6365601/default-sub-command-or-handling-no-sub-command-with-argparse
    """
    subparser_found = False
    for arg in sys.argv[1:]:
        if arg in ['-h', '--help']:  # global help if no subparser
            break
    else:
        for x in self._subparsers._actions:  # pylint: disable=W0212
            if not isinstance(
                x, argparse._SubParsersAction
            ):  # pylint: disable=W0212
                continue
            for sp_name in x._name_parser_map.keys(
            ):  # pylint: disable=W0201,W0212
                if sp_name in sys.argv[1:]:
                    subparser_found = True
        if not subparser_found:
            # insert default in first position, this implies no
            # global options without a sub_parsers specified
            if args is None:
                sys.argv.insert(1, name)
            else:
                args.insert(0, name)


argparse.ArgumentParser.set_default_subparser = set_default_subparser


def main(argv):  # pylint: disable=W0613
    parser = argparse.ArgumentParser()
    mode = parser.add_subparsers(dest='mode', help='commands')

    wizard = mode.add_parser('wizard', help='Runs setup wizard')
    wizard.add_argument(
        '--dialog-release',
        action='store',
        default='3',
        help='Display the Choose Release Dialog'
    )
    wizard.add_argument(
        '--dir',
        dest='dir_builder',
        action='store',
        default=None,
        help='Location path of vanir-builder base directory'
    )
    wizard.add_argument(
        '-c',
        dest='config_filename',
        action='store',
        default='.setup.data',
        help='Setup configuration file'
    )
    wizard.add_argument(
        '--development',
        '--dev',
        dest='development',
        action='store_true',
        default=DEVELOPMENT_MODE,
        help='include in-progress development configuration options'
    )

    info = mode.add_parser('info', help='Display builder configuration')
    info.add_argument(
        '-c',
        dest='config_filename',
        action='store',
        default=BUILDER_CONF,
        help='configuration file ({0})'.format(BUILDER_CONF)
    )

    # pylint: disable=W0612
    depends = mode.add_parser(
        'install-deps',
        help='Install build dependencies'
    )

    parser.set_default_subparser('wizard')
    args = vars(parser.parse_args())
    mode = args['mode']

    if mode == 'wizard':
        Wizard(DialogUI(), **args)()
    elif mode == 'info':
        display_configuration(args['config_filename'])
    elif mode == 'install-deps':
        install_deps()


try:
    import sh
except ImportError:
    install_deps(['python2-sh'])
    import sh

if __name__ == '__main__':
    # Make sure dependencies are all installed
    install_deps()

    main(sys.argv)
    sys.exit(0)
