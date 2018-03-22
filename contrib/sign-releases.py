#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sign releases on github

Settings is read from options, then if repo not set, repo is read from
current dire 'git remote -v' output, filtered by 'origin', then config
file is read.

If setting is already set then it value does not changes.

Config file can have one repo form or multiple repo form.

In one repo form config settings read from root JSON object.
Keys are "repo", "keyid", "token", "count" and "sign_drafts",
which is correspond to program options.

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
import sys
import time
import getpass
import shutil
import hashlib
import tempfile
import json
from subprocess import check_output, CalledProcessError

try:
    import click
    import gnupg
    import dateutil.parser
    import colorama
    from colorama import Fore, Style
    from github_release import (get_releases, gh_asset_download,
                                gh_asset_upload, gh_asset_delete)
except ImportError, e:
    print 'Import error:', e
    print 'To run script install required packages with the next command:\n\n'\
          'pip install githubrelease python-gnupg pyOpenSSL cryptography idna'\
          ' certifi python-dateutil click colorama'
    sys.exit(1)


HOME_DIR = os.path.expanduser('~')
CONFIG_NAME = '.sign-releases'
SEARCH_COUNT = 6
SHA_FNAME = 'SHA256SUMS.txt'


def compare_published_times(a, b):
    """Releases list sorting comparsion function"""

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
    except Exception, e:
        print 'Error: Cannot read config file:', e
        return {}


def check_github_repo(remote_name='origin'):
    """Try to determine and return 'username/repo' if current dir is git dir"""
    try:
        remotes = check_output(['git', 'remote', '-v'],
                               stderr=open(os.devnull, 'w'))
        remotes = remotes.splitlines()
    except CalledProcessError:
        remotes = []
    remotes = [r for r in remotes if remote_name in r]
    repo = remotes[0].split()[1] if len(remotes) > 0 else None

    if repo:
        if repo.startswith('git'):
            repo = repo.split(':')[-1]

        if repo.startswith('http'):
            if repo.endswith('/'):
                repo = repo[:-1]

            repo = repo.split('/')
            repo = '/'.join(repo[-2:])

        if repo.endswith('.git'):
            repo = repo[:-4]

    return repo


class ChdirTemporaryDirectory(object):
    """Create tmp dir, chdir to it and remove on exit"""
    def __enter__(self):
        self.name = tempfile.mkdtemp()
        os.chdir(self.name)
        return self.name

    def __exit__(self, exc_type, exc_value, traceback):
        shutil.rmtree(self.name)


class SignApp(object):
    def __init__(self, **kwargs):
        """Get app settings from options, from curdir git, from config file"""
        ask_passphrase = kwargs.pop('ask_passphrase', None)
        self.sign_drafts = kwargs.pop('sign_drafts', False)
        self.force = kwargs.pop('force', False)
        self.tag_name = kwargs.pop('tag_name', None)
        self.repo = kwargs.pop('repo', None)
        self.token = kwargs.pop('token', None)
        self.keyid = kwargs.pop('keyid', None)
        self.count = kwargs.pop('count', None)
        self.dry_run = kwargs.pop('dry_run', False)

        if not self.repo:
            self.repo = check_github_repo()

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
            self.token = self.token or self.config.get('token', None)
            self.keyid = self.keyid or self.config.get('keyid', None)
            self.count = self.count or self.config.get('count', None) \
                or SEARCH_COUNT
            self.sign_drafts = self.sign_drafts \
                or self.config.get('sign_drafts', False)

        if not self.repo:
            print 'no repo found, exit'
            sys.exit(1)

        if self.token:
            os.environ['GITHUB_TOKEN'] = self.token

        if not os.environ.get('GITHUB_TOKEN', None):
            print 'GITHUB_TOKEN environment var not set, exit'
            sys.exit(1)

        if self.keyid:
            self.keyid = self.keyid.split('/')[-1]

        self.passphrase = None
        self.gpg = gnupg.GPG()

        if not self.keyid:
            print 'no keyid set, exit'
            sys.exit(1)

        keylist = self.gpg.list_keys(True, keys=[self.keyid])
        if not keylist:
            print 'no key with keyid %s found, exit' % self.keyid
            sys.exit(1)

        self.uid = ', '.join(keylist[0].get('uids', ['No uid found']))

        if ask_passphrase:
            while not self.passphrase:
                self.read_passphrase()
        elif not self.check_key():
            while not self.passphrase:
                self.read_passphrase()

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
        print '%sWrong passphrase!%s' % (Fore.RED, Style.RESET_ALL)
        return False

    def sign_file_name(self, name, detach=True):
        """Sign file with self.keyid, place signature in deteached .asc file"""
        with open(name, 'rb') as fdrb:
            signed_data = self.gpg.sign_file(fdrb,
                                             keyid=self.keyid,
                                             passphrase=self.passphrase,
                                             detach=detach)
            with open('%s.asc' % name, 'w') as fdw:
                fdw.write(signed_data.data)

    def sign_release(self, release, other_names, asc_names):
        """Download/sign unsigned assets, upload .asc counterparts.
        Create SHA256SUMS.txt with all assets included and upload it
        with SHA256SUMS.txt.asc counterpart.
        """
        repo = self.repo
        tag = release.get('tag_name', None)
        if not tag:
            print 'Release have no tag name, skip release\n'
            return

        with ChdirTemporaryDirectory():
            with open(SHA_FNAME, 'w') as fdw:
                for name in other_names:
                    if name == SHA_FNAME:
                        continue

                    gh_asset_download(repo, tag, name)
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

    def search_and_sign_unsinged(self):
        """Search through last 'count' releases with assets without
        .asc counterparts or releases withouth SHA256SUMS.txt.asc
        """
        print 'Sign releases on repo: %s' % self.repo
        print '  With key: %s, %s\n' % (self.keyid, self.uid)
        releases = get_releases(self.repo)

        if self.tag_name:
            releases = [r for r in releases
                        if r.get('tag_name', None) == self.tag_name]

            if len(releases) == 0:
                print 'No release with tag "%s" found, exit' % self.tag_name
                sys.exit(1)
        elif not self.sign_drafts:
            releases = [r for r in releases if not r.get('draft', False)]

        # cycle through releases sorted by by publication date
        releases.sort(compare_published_times)
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

            print msg

            asset_names = [a['name'] for a in r['assets']]

            if not asset_names:
                print '  No assets found, skip release\n'
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
                self.sign_release(r, other_names, asc_names)
            else:
                print '  Seems already signed, skip release\n'


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.command(context_settings=CONTEXT_SETTINGS)
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
def main(**kwargs):
    app = SignApp(**kwargs)

    sleep = kwargs.pop('sleep', None)
    if (sleep):
        print 'Sleep for %s seconds' % sleep
        time.sleep(sleep)

    app.search_and_sign_unsinged()


if __name__ == '__main__':
    colorama.init()
    main()
