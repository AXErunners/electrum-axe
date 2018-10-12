#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sign releases on github, make/upload ppa to launchpad.net

NOTE on ppa: To build a ppa you may need to install some more packages.
On ubuntu:

     sudo apt-get install devscripts libssl-dev python3-dev \
          debhelper python3-setuptools dh-python

NOTE on apk signing: To create a keystore and sign the apk you need to install
      java-8-openjdk, or java-7-openjdk on older systems.

To create a keystore run the following command:

    mkdir ~/.jks && keytool -genkey -v -keystore ~/.jks/keystore \
        -alias electrum.dash.org -keyalg RSA -keysize 2048 \
        -validity 10000

Then it shows a warning about the proprietary format and a command to migrate:

    keytool -importkeystore -srckeystore ~/.jks/keystore \
            -destkeystore ~/.jks/keystore -deststoretype pkcs12

Manual signing:

    jarsigner -verbose \
        -tsa http://sha256timestamp.ws.symantec.com/sha256/timestamp \
        -sigalg SHA1withRSA -digestalg SHA1 \
        -sigfile dash-electrum \
        -keystore ~/.jks/keystore \
        Electrum_DASH-3.0.6.1-release-unsigned.apk \
        electrum.dash.org

Zipalign from Android SDK build tools is also required (set path to bin in
settings file or with key -z). To install:

    wget http://dl.google.com/android/android-sdk_r24-linux.tgz \
    && tar xzf android-sdk_r24-linux.tgz \
    && rm android-sdk_r24-linux.tgz \
    && (while sleep 3; do echo "y"; done) \
        | android-sdk-linux/tools/android update sdk -u -a -t \
            'tools, platform-tools-preview, build-tools-23.0.1' \
    && (while sleep 3; do echo "y"; done) \
        | android-sdk-linux/tools/android update sdk -u -a -t \
            'tools, platform-tools, build-tools-27.0.3'

Manual zip aligning:

    android-sdk-linux/build-tools/27.0.3/zipalign -v 4 \
        Electrum_DASH-3.0.6.1-release-unsigned.apk \
        Dash-Electrum-3.0.6.1-release.apk



About script settings:

Settings is read from options, then config file is read.
If setting is already set from options, then it value does
not changes.

Config file can have one repo form or multiple repo form.

In one repo form config settings read from root JSON object.
Keys are "repo", "keyid", "token", "count", "sign_drafts",
and others, which is corresponding to program options.

Example:

    {
        "repo": "value"
        ...
    }

In multiple repo form, if root "default_repo" key is set, then code
try to read "repos" key as list and cycle through it to find suitable
repo, or if no repo is set before, then "default_repo" is used to match.
If match found, then that list object is used ad one repo form config.

Example:

    {
        "default_repo": "value"
        "repos": [
            {
                "repo": "value"
                ...
            }
        ]
    }
"""

import os
import os.path
import re
import sys
import time
import getpass
import shutil
import hashlib
import tempfile
import json
import zipfile
from subprocess import check_call, CalledProcessError
from functools import cmp_to_key
from time import localtime, strftime

try:
    import click
    import certifi
    import gnupg
    import dateutil.parser
    import colorama
    from colorama import Fore, Style
    from github_release import (get_releases, gh_asset_download,
                                gh_asset_upload, gh_asset_delete,
                                gh_release_edit)
    from urllib3 import PoolManager
except ImportError as e:
    print('Import error:', e)
    print('To run script install required packages with the next command:\n\n'
          'pip install githubrelease python-gnupg pyOpenSSL cryptography idna'
          ' certifi python-dateutil click colorama requests LinkHeader')
    sys.exit(1)

HTTP = PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())

FNULL = open(os.devnull, 'w')

HOME_DIR = os.path.expanduser('~')
CONFIG_NAME = '.sign-releases'
SEARCH_COUNT = 1
SHA_FNAME = 'SHA256SUMS.txt'

# make_ppa related definitions
PPA_SERIES = {
    'trusty': '14.04.1',
    'xenial': '16.04.1',
    'bionic': '18.04.1',
    'cosmic': '18.10.1',
}
PEP440_PUBVER_PATTERN = re.compile('^((\d+)!)?'
                                   '((\d+)(\.\d+)*)'
                                   '([a-zA-Z]+\d+)?'
                                   '((\.[a-zA-Z]+\d+)*)$')
REL_NOTES_PATTERN = re.compile('^#.+?(^[^#].+?)^#.+?', re.M | re.S)
SDIST_NAME_PATTERN = re.compile('^Dash-Electrum-(.*).tar.gz$')
SDIST_DIR_TEMPLATE = 'Dash-Electrum-{version}'
PPA_SOURCE_NAME = 'electrum-dash'
PPA_ORIG_NAME_TEMPLATE = '%s_{version}.orig.tar.gz' % PPA_SOURCE_NAME
CHANGELOG_TEMPLATE = """%s ({ppa_version}) {series}; urgency=medium
{changes} -- {uid}  {time}""" % PPA_SOURCE_NAME
PPA_FILES_TEMPLATE = '%s_{0}{1}' % PPA_SOURCE_NAME
LP_API_URL='https://api.launchpad.net/1.0'
LP_SERIES_TEMPLATE = '%s/ubuntu/{0}' % LP_API_URL
LP_ARCHIVES_TEMPLATE = '%s/~{user}/+archive/ubuntu/{ppa}' % LP_API_URL

# sing_apk related definitions
JKS_KEYSTORE = os.path.join(HOME_DIR, '.jks/keystore')
JKS_ALIAS = 'electrum.dash.org'
JKS_STOREPASS = 'JKS_STOREPASS'
JKS_KEYPASS = 'JKS_KEYPASS'
KEYTOOL_ARGS = ['keytool', '-list', '-storepass:env', JKS_STOREPASS]
JARSIGNER_ARGS = [
    'jarsigner', '-verbose',
    '-tsa', 'http://sha256timestamp.ws.symantec.com/sha256/timestamp',
    '-sigalg', 'SHA1withRSA', '-digestalg', 'SHA1',
    '-sigfile', 'dash-electrum',
    '-storepass:env', JKS_STOREPASS,
    '-keypass:env', JKS_KEYPASS,
]
UNSIGNED_APK_PATTERN = re.compile('^Electrum_DASH-(.*)-release-unsigned.apk$')
SIGNED_APK_TEMPLATE = 'Dash-Electrum-{version}-release.apk'


os.environ['QUILT_PATCHES'] = 'debian/patches'


def pep440_to_deb(version):
    """Convert PEP 440 public version to deb upstream version"""
    ver_match = PEP440_PUBVER_PATTERN.match(version)
    if not ver_match:
        raise Exception('Version "%s" does not comply with PEP 440' % version)

    g = ver_match.group
    deb_ver = ''
    deb_ver += ('%s:' % g(2)) if g(1) else ''
    deb_ver += g(3)
    deb_ver += ('~%s' % g(6)) if g(6) else ''
    deb_ver += ('%s' % g(7)) if g(7) else ''

    return deb_ver


def compare_published_times(a, b):
    """Releases list sorting comparsion function (last published first)"""

    a = a['published_at']
    b = b['published_at']

    if not a and not b:
        return 0
    elif not a:
        return -1
    elif not b:
        return 1

    a = dateutil.parser.parse(a)
    b = dateutil.parser.parse(b)

    if a > b:
        return -1
    elif b > a:
        return 1
    else:
        return 0


def sha256_checksum(filename, block_size=65536):
    """Gather sha256 hash on filename"""
    sha256 = hashlib.sha256()
    with open(filename, 'rb') as f:
        for block in iter(lambda: f.read(block_size), b''):
            sha256.update(block)
    return sha256.hexdigest()


def read_config():
    """Read and parse JSON from config file from HOME dir"""
    config_path = os.path.join(HOME_DIR, CONFIG_NAME)
    if not os.path.isfile(config_path):
        return {}

    try:
        with open(config_path, 'r') as f:
            data = f.read()
            return json.loads(data)
    except Exception as e:
        print('Error: Cannot read config file:', e)
        return {}


def get_next_ppa_num(ppa, source_package_name, ppa_upstr_version, series_name):
    """Calculate next ppa num (if older ppa versions whas published earlier)"""
    user, ppa_name = ppa.split('/')
    archives_url = LP_ARCHIVES_TEMPLATE.format(user=user, ppa=ppa_name)
    series_url = LP_SERIES_TEMPLATE.format(series_name)
    query = {
        'ws.op': 'getPublishedSources',
        'distro_series': series_url,
        'order_by_date': 'true',
        'source_name': source_package_name,
    }

    resp = HTTP.request('GET', archives_url, fields=query)
    if resp.status != 200:
        raise Exception('Launchpad API error %s %s', (resp.status,
                                                      resp.reason))
    data = json.loads(resp.data.decode('utf-8'))
    entries = data['entries']
    if len(entries) == 0:
        return 1

    for e in entries:
        ppa_version = e['source_package_version']
        version_match = re.match('%s-0ppa(\d+)~ubuntu' % ppa_upstr_version,
                                 ppa_version)
        if version_match:
            return int(version_match.group(1)) + 1

    return 1


class ChdirTemporaryDirectory(object):
    """Create tmp dir, chdir to it and remove on exit"""
    def __enter__(self):
        self.prev_wd = os.getcwd()
        self.name = tempfile.mkdtemp()
        os.chdir(self.name)
        return self.name

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.prev_wd)
        shutil.rmtree(self.name)


class SignApp(object):
    def __init__(self, **kwargs):
        """Get app settings from options, from curdir git, from config file"""
        ask_passphrase = kwargs.pop('ask_passphrase', None)
        self.sign_drafts = kwargs.pop('sign_drafts', False)
        self.force = kwargs.pop('force', False)
        self.tag_name = kwargs.pop('tag_name', None)
        self.repo = kwargs.pop('repo', None)
        self.ppa = kwargs.pop('ppa', None)
        self.ppa_upstream_suffix = kwargs.pop('ppa_upstream_suffix', None)
        self.token = kwargs.pop('token', None)
        self.keyid = kwargs.pop('keyid', None)
        self.count = kwargs.pop('count', None)
        self.dry_run = kwargs.pop('dry_run', False)
        self.no_ppa = kwargs.pop('no_ppa', False)
        self.verbose = kwargs.pop('verbose', False)
        self.jks_keystore = kwargs.pop('jks_keystore', False)
        self.jks_alias = kwargs.pop('jks_alias', False)
        self.zipalign_path = kwargs.pop('zipalign_path', False)

        self.config = {}
        config_data = read_config()

        default_repo = config_data.get('default_repo', None)
        if default_repo:
            if not self.repo:
                self.repo = default_repo

            for config in config_data.get('repos', []):
                config_repo = config.get('repo', None)
                if config_repo and config_repo == self.repo:
                    self.config = config
                    break
        else:
            self.config = config_data

        if self.config:
            self.repo = self.repo or self.config.get('repo', None)
            self.ppa = self.ppa or self.config.get('ppa', None)
            self.token = self.token or self.config.get('token', None)
            self.keyid = self.keyid or self.config.get('keyid', None)
            self.count = self.count or self.config.get('count', None) \
                or SEARCH_COUNT
            self.sign_drafts = self.sign_drafts \
                or self.config.get('sign_drafts', False)
            self.no_ppa = self.no_ppa \
                or self.config.get('no_ppa', False)
            self.verbose = self.verbose or self.config.get('verbose', None)
            self.jks_keystore = self.jks_keystore \
                or self.config.get('jks_keystore', JKS_KEYSTORE)
            self.jks_alias = self.jks_alias \
                or self.config.get('jks_alias', JKS_ALIAS)
            self.zipalign_path = self.zipalign_path \
                or self.config.get('zipalign_path', None)

        if not self.repo:
            print('no repo found, exit')
            sys.exit(1)

        if self.token:
            os.environ['GITHUB_TOKEN'] = self.token

        if not os.environ.get('GITHUB_TOKEN', None):
            print('GITHUB_TOKEN environment var not set, exit')
            sys.exit(1)

        if self.keyid:
            self.keyid = self.keyid.split('/')[-1]

        self.passphrase = None
        self.gpg = gnupg.GPG()

        if not self.keyid:
            print('no keyid set, exit')
            sys.exit(1)

        keylist = self.gpg.list_keys(True, keys=[self.keyid])
        if not keylist:
            print('no key with keyid %s found, exit' % self.keyid)
            sys.exit(1)

        self.uid = ', '.join(keylist[0].get('uids', ['No uid found']))

        if ask_passphrase:
            while not self.passphrase:
                self.read_passphrase()
        elif not self.check_key():
            while not self.passphrase:
                self.read_passphrase()

        if self.zipalign_path:
            try:
                check_call(self.zipalign_path, stderr=FNULL)
            except CalledProcessError:
                pass
            self.read_jks_storepass()
            self.read_jks_keypass()

    def read_jks_storepass(self):
        """Read JKS storepass and keypass"""
        while not JKS_STOREPASS in os.environ:
            storepass = getpass.getpass('%sInput %s keystore password:%s ' %
                                    (Fore.GREEN,
                                     self.jks_keystore,
                                     Style.RESET_ALL))
            os.environ[JKS_STOREPASS] = storepass
            try:
                check_call(KEYTOOL_ARGS + ['-keystore', self.jks_keystore],
                       stdout=FNULL, stderr=FNULL)
            except CalledProcessError:
                print('%sWrong keystore password%s' %
                      (Fore.RED, Style.RESET_ALL))
                del os.environ[JKS_STOREPASS]

    def read_jks_keypass(self):
        while not JKS_KEYPASS in os.environ:
            keypass = getpass.getpass('%sInput alias password for <%s> '
                                      '[Enter if same as for keystore]:%s ' %
                                  (Fore.YELLOW,
                                   self.jks_alias,
                                   Style.RESET_ALL))
            if not keypass:
                os.environ[JKS_KEYPASS] = os.environ[JKS_STOREPASS]
            else:
                os.environ[JKS_KEYPASS] = keypass

            with ChdirTemporaryDirectory() as tmpdir:
                test_file = 'testfile.txt'
                test_zipfile = 'testzip.zip'
                with open(test_file, 'w') as fdw:
                    fdw.write('testcontent')
                test_zf = zipfile.ZipFile(test_zipfile, mode='w')
                test_zf.write(test_file)
                test_zf.close()

                sign_args = ['-keystore', self.jks_keystore,
                             test_zipfile, self.jks_alias]
                try:
                    check_call(JARSIGNER_ARGS + sign_args, stdout=FNULL)
                except CalledProcessError:
                    print('%sWrong key alias password%s' %
                          (Fore.RED, Style.RESET_ALL))
                    del os.environ[JKS_KEYPASS]

    def read_passphrase(self):
        """Read passphrase for gpg key until check_key is passed"""
        passphrase = getpass.getpass('%sInput passphrase for Key: %s %s:%s ' %
                                     (Fore.GREEN,
                                      self.keyid,
                                      self.uid,
                                      Style.RESET_ALL))
        if self.check_key(passphrase):
            self.passphrase = passphrase

    def check_key(self, passphrase=None):
        """Try to sign test string, and if some data signed retun True"""
        signed_data = self.gpg.sign('test message to check passphrase',
                                    keyid=self.keyid, passphrase=passphrase)
        if signed_data.data and self.gpg.verify(signed_data.data).valid:
            return True
        print('%sWrong passphrase!%s' % (Fore.RED, Style.RESET_ALL))
        return False

    def sign_file_name(self, name, detach=True):
        """Sign file with self.keyid, place signature in deteached .asc file"""
        with open(name, 'rb') as fdrb:
            signed_data = self.gpg.sign_file(fdrb,
                                             keyid=self.keyid,
                                             passphrase=self.passphrase,
                                             detach=detach)
            with open('%s.asc' % name, 'wb') as fdw:
                fdw.write(signed_data.data)

    def sign_release(self, release, other_names, asc_names, is_newest_release):
        """Download/sign unsigned assets, upload .asc counterparts.
        Create SHA256SUMS.txt with all assets included and upload it
        with SHA256SUMS.txt.asc counterpart.
        """
        repo = self.repo
        tag = release.get('tag_name', None)
        if not tag:
            print('Release have no tag name, skip release\n')
            return

        with ChdirTemporaryDirectory() as tmpdir:
            with open(SHA_FNAME, 'w') as fdw:
                sdist_match = None
                for name in other_names:
                    if name == SHA_FNAME:
                        continue

                    gh_asset_download(repo, tag, name)

                    if not self.no_ppa:
                        sdist_match = sdist_match \
                                      or SDIST_NAME_PATTERN.match(name)

                    apk_match = UNSIGNED_APK_PATTERN.match(name)
                    if apk_match:
                        unsigned_name = name
                        name = self.sign_apk(unsigned_name, apk_match.group(1))

                        gh_asset_upload(repo, tag, name, dry_run=self.dry_run)
                        gh_asset_delete(repo, tag, unsigned_name,
                                        dry_run=self.dry_run)

                    if not '%s.asc' % name in asc_names or self.force:
                        self.sign_file_name(name)

                        if self.force:
                            gh_asset_delete(repo, tag, '%s.asc' % name,
                                            dry_run=self.dry_run)

                        gh_asset_upload(repo, tag, '%s.asc' % name,
                                        dry_run=self.dry_run)

                    sumline = '%s %s\n' % (sha256_checksum(name), name)
                    fdw.write(sumline)

            self.sign_file_name(SHA_FNAME, detach=False)

            gh_asset_delete(repo, tag, '%s.asc' % SHA_FNAME,
                            dry_run=self.dry_run)

            gh_asset_upload(repo, tag, '%s.asc' % SHA_FNAME,
                            dry_run=self.dry_run)

            if sdist_match and is_newest_release:
                self.make_ppa(sdist_match, tmpdir, tag)

    def sign_apk(self, unsigned_name, version):
        """Sign unsigned release apk"""
        if not (JKS_STOREPASS in os.environ and JKS_KEYPASS in os.environ):
            raise Exception('Found unsigned apk and no zipalign path set')

        name = SIGNED_APK_TEMPLATE.format(version=version)

        print('Signing apk: %s' % name)
        apk_args = ['-keystore', self.jks_keystore,
                    unsigned_name, self.jks_alias]
        if self.verbose:
            check_call(JARSIGNER_ARGS + apk_args)
            check_call([self.zipalign_path, '-v', '4', unsigned_name, name])
        else:
            check_call(JARSIGNER_ARGS + apk_args, stdout=FNULL)
            check_call([self.zipalign_path, '-v', '4', unsigned_name, name],
                       stdout=FNULL)

        return name

    def make_ppa(self, sdist_match, tmpdir, tag):
        """Build, sign and upload dsc to launchpad.net ppa from sdist.tar.gz"""
        repo = self.repo

        with ChdirTemporaryDirectory() as ppa_tmpdir:
            sdist_name = sdist_match.group(0)
            version = sdist_match.group(1)
            ppa_upstr_version = pep440_to_deb(version)
            ppa_upstream_suffix = self.ppa_upstream_suffix
            if ppa_upstream_suffix:
                ppa_upstr_version += ('+%s' % ppa_upstream_suffix)
            ppa_orig_name = PPA_ORIG_NAME_TEMPLATE.format(
                version=ppa_upstr_version)
            series = list(map(lambda x: x[0],
                sorted(PPA_SERIES.items(), key=lambda x: x[1])))
            sdist_dir = SDIST_DIR_TEMPLATE.format(version=version)
            sdist_dir = os.path.join(ppa_tmpdir, sdist_dir)
            debian_dir = os.path.join(sdist_dir, 'debian')
            changelog_name = os.path.join(debian_dir, 'changelog')
            relnotes_name = os.path.join(sdist_dir, 'RELEASE-NOTES')

            print('Found sdist: %s, version: %s' % (sdist_name, version))
            print('  Copying sdist to %s, extracting' % ppa_orig_name)
            shutil.copy(os.path.join(tmpdir, sdist_name),
                  os.path.join(ppa_tmpdir, ppa_orig_name))
            check_call(['tar', '-xzvf', ppa_orig_name], stdout=FNULL)

            with open(relnotes_name, 'r') as rnfd:
                changes = rnfd.read()
                changes_match = REL_NOTES_PATTERN.match(changes)
                if changes_match and len(changes_match.group(1)) > 0:
                    changes = changes_match.group(1).split('\n')
                    for i in range(len(changes)):
                        if changes[i] == '':
                            continue
                        elif changes[i][0] != ' ':
                            changes[i] = '  %s' % changes[i]
                        elif len(changes[i]) > 1 and changes[i][1] != ' ':
                            changes[i] = ' %s' % changes[i]
                    changes = '\n'.join(changes)
                else:
                    changes = '\n  * Porting to ppa\n\n'

            if not self.dry_run:
                gh_release_edit(repo, tag, name=version)
                gh_release_edit(repo, tag, body=changes)

            os.chdir(sdist_dir)
            print('  Making PPAs for series: %s' % (', '.join(series)))
            now_formatted = strftime('%a, %d %b %Y %H:%M:%S %z', localtime())
            for s in series:
                ppa_num = get_next_ppa_num(self.ppa, PPA_SOURCE_NAME,
                                           ppa_upstr_version, s)
                rel_version = PPA_SERIES[s]
                ppa_version = '%s-0ppa%s~ubuntu%s' % (ppa_upstr_version,
                                                      ppa_num, rel_version)
                ppa_dsc = os.path.join(ppa_tmpdir, PPA_FILES_TEMPLATE.format(
                    ppa_version, '.dsc'))
                ppa_chgs = os.path.join(ppa_tmpdir, PPA_FILES_TEMPLATE.format(
                    ppa_version, '_source.changes'))
                changelog = CHANGELOG_TEMPLATE.format(ppa_version=ppa_version,
                                                      series=s,
                                                      changes=changes,
                                                      uid=self.uid,
                                                      time=now_formatted)

                with open(changelog_name, 'w') as chlfd:
                    chlfd.write(changelog)

                print('  Make %s ppa, Signing with key: %s, %s' %
                    (ppa_version, self.keyid, self.uid))
                if self.verbose:
                    check_call(['debuild', '-S'])
                else:
                    check_call(['debuild', '-S'], stdout=FNULL)
                print('  Upload %s ppa to %s' % (ppa_version, self.ppa))
                if self.dry_run:
                    print('  Dry run:  dput ppa:%s %s' % (self.ppa, ppa_chgs))
                else:
                    check_call(['dput', ('ppa:%s' % self.ppa), ppa_chgs],
                         stdout=FNULL)
                print('\n')

    def search_and_sign_unsinged(self):
        """Search through last 'count' releases with assets without
        .asc counterparts or releases withouth SHA256SUMS.txt.asc
        """
        print('Sign releases on repo: %s' % self.repo)
        print('  With key: %s, %s\n' % (self.keyid, self.uid))
        releases = get_releases(self.repo)

        if self.tag_name:
            releases = [r for r in releases
                        if r.get('tag_name', None) == self.tag_name]

            if len(releases) == 0:
                print('No release with tag "%s" found, exit' % self.tag_name)
                sys.exit(1)
        elif not self.sign_drafts:
            releases = [r for r in releases if not r.get('draft', False)]

        # cycle through releases sorted by by publication date
        releases.sort(key=cmp_to_key(compare_published_times))
        for r in releases[:self.count]:
            tag_name = r.get('tag_name', 'No tag_name')
            is_draft = r.get('draft', False)
            is_prerelease = r.get('prerelease', False)
            created_at = r.get('created_at', '')

            msg = 'Found %s%s tagged: %s, created at: %s' % (
                'draft ' if is_draft else '',
                'prerelease' if is_prerelease else 'release',
                tag_name,
                created_at
            )

            if not is_draft:
                msg += ', published at: %s' % r.get('published_at', '')

            print(msg)

            asset_names = [a['name'] for a in r['assets']]

            if not asset_names:
                print('  No assets found, skip release\n')
                continue

            asc_names = [a for a in asset_names if a.endswith('.asc')]
            other_names = [a for a in asset_names if not a.endswith('.asc')]
            need_to_sign = False

            if asset_names and not asc_names:
                need_to_sign = True

            if not need_to_sign:
                for name in other_names:
                    if not '%s.asc' % name in asc_names:
                        need_to_sign = True
                        break

            if not need_to_sign:
                need_to_sign = '%s.asc' % SHA_FNAME not in asc_names

            if need_to_sign or self.force:
                self.sign_release(r, other_names, asc_names, r==releases[0])
            else:
                print('  Seems already signed, skip release\n')


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-a', '--jks-alias',
              help='jks key alias')
@click.option('-c', '--count', type=int,
              help='Number of recently published releases to sign')
@click.option('-d', '--sign-drafts', is_flag=True,
              help='Sing draft releases first')
@click.option('-f', '--force', is_flag=True,
              help='Sing already signed releases')
@click.option('-g', '--tag-name',
              help='Sing only release tagged with tag name')
@click.option('-k', '--keyid',
              help='gnupg keyid')
@click.option('-K', '--jks-keystore',
              help='jks keystore path')
@click.option('-l', '--ppa',
              help='PPA in format uzername/ppa')
@click.option('-S', '--ppa-upstream-suffix',
              help='upload upstream source with version suffix (ex p1)')
@click.option('-L', '--no-ppa', is_flag=True,
              help='Do not make launchpad ppa')
@click.option('-n', '--dry-run', is_flag=True,
              help='Do not uload signed files')
@click.option('-p', '--ask-passphrase', is_flag=True,
              help='Ask to enter passphrase')
@click.option('-r', '--repo',
              help='Repository in format username/reponame')
@click.option('-s', '--sleep', type=int,
              help='Sleep number of seconds before signing')
@click.option('-t', '--token',
              help='GigHub access token, to be set as'
                   ' GITHUB_TOKEN environmet variable')
@click.option('-v', '--verbose', is_flag=True,
              help='Make more verbose output')
@click.option('-z', '--zipalign-path',
              help='zipalign path')
def main(**kwargs):
    app = SignApp(**kwargs)

    sleep = kwargs.pop('sleep', None)
    if (sleep):
        print('Sleep for %s seconds' % sleep)
        time.sleep(sleep)

    app.search_and_sign_unsinged()


if __name__ == '__main__':
    colorama.init()
    main()
