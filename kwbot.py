#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# KwBot
# A simple, opinionated Python/Twisted bot.
# Copyright © 2015-2021, Chris Warrick.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions, and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions, and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the author of this software nor the names of
#    contributors to this software may be used to endorse or promote
#    products derived from this software without specific prior written
#    consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
    KwBot
    =====
    A simple, opinionated Python/Twisted bot.

    Website/docs: https://chriswarrick.com/kwbot/
    Parts based on: http://bit.ly/ircbot/
"""

# -*- coding: utf-8 -*-

import datetime
import sys
import os
import re
import json
import hmac
import hashlib

from twisted.internet import defer, protocol, ssl
from twisted.python import log
from twisted.words.protocols import irc
from twisted.web import server, resource
from twisted.internet import reactor

try:
    import systemd.daemon
except ImportError:
    systemd = None

# Settings.
HOME = '/home/kwpolska/virtualenvs/kwbot'
CONFHOME = '/home/kwpolska/git/kwbot.conf'
LOGDIR = HOME + '/logs'
ADMIN = 'ChrisWarrick'
NIKOLOGS = '/home/kwpolska/nikola-logs/logs'
GHISSUES_TXT = u'[\00313{repo}\017] \00315{actor}\017 {action} {type} \002#{number}\017: {title} \00302\037{url}\017'
GHISSUES_ASSIGN = u'[\00313{repo}\017] \00315{actor}\017 {action} {type} \002#{number}\017 to \00315{assignee}\017: {title} \00302\037{url}\017'
GHISSUES_PR = u'[\00313{repo}\017] \00315{actor}\017 {action} {type} \002#{number}\017 (\00310{head}\017): {title} \00302\037{url}\017'
GHISSUES_ASSIGN_PR = u'[\00313{repo}\017] \00315{actor}\017 {action} {type} \002#{number}\017 (\00310{head}\017) to \00315{assignee}\017: {title} \00302\037{url}\017'
GHISSUES_REVIEW = u'[\00313{repo}\017] \00315{actor}\017 requested review on {type} \002#{number}\017 (\00310{head}\017) from \00315{reviewer}\017: {title} \00302\037{url}\017'
GHISSUES_UNREVIEW = u'[\00313{repo}\017] \00315{actor}\017 removed review request on {type} \002#{number}\017 (\00310{head}\017) from \00315{reviewer}\017: {title} \00302\037{url}\017'

with open(CONFHOME + '/channels.txt') as fh:
    CHANNELS = [l.strip().split(",") for l in fh]

# A regexp to recognize commands.
CMDR = re.compile(r'(KwBot.? |!)(?P<command>\S+)(?P<args> .*)?', re.U | re.I)
# A regexp to remove all mIRC colors.
COLR = re.compile('(\x03\\d\\d?|\x03\\d\\d?,\\d\\d?|\x02|\x0f|\x16|\x1d|\x1f)')

BOT = []
READY_BOTS = 0
READY_EXPECTED = 1


class KwBotIRCProtocol(irc.IRCClient):
    nickname = 'KwBot'
    realname = 'Chris Warrick’s Friendly Bot'
    versionName = 'KwBot'
    identified = False

    def __init__(self):
        global BOT
        BOT.append(self)
        self.deferred = defer.Deferred()
        self.toBeDelivered = {}
        self.factoids = {}
        self.fcount = self.load_factoids()

    @property
    def network(self):
        if "freenode" in self.hostname:
            return "freenode"
        elif "libera" in self.hostname:
            return "libera"
        return "?"

    def connectionLost(self, reason):
        self.deferred.errback(reason)

    def signedOn(self):
        global READY_BOTS
        with open(CONFHOME + '/password.txt') as fh:
            NICKSERV_PWD = fh.read().strip()
        self.msg('NickServ', 'identify KwBot {0}'.format(NICKSERV_PWD))
        READY_BOTS += 1
        if READY_BOTS == READY_EXPECTED and systemd is not None:
            systemd.daemon.notify("READY=1")

    def joined(self, channel):
        log.msg('joined ' + channel)

    def _logmsg(self, channel, nick, message, notice=False, action=False):
        """Log a message."""
        cd = os.path.join(LOGDIR, channel)
        if channel != '#nikola' and not os.path.exists(cd):
            os.makedirs(cd)
        dt = datetime.datetime.now(datetime.UTC)
        date = dt.strftime('%Y-%m-%d')
        time = dt.strftime('%H:%M:%S')
        if notice:
            nickg = '-{0}:{1}-'.format(nick, channel)
        elif action:
            nickg = '* {0}'.format(nick)
        else:
            nickg = '<{0}>'.format(nick)
        message = COLR.sub('', message)
        if channel == '#nikola':
            with open(os.path.join(NIKOLOGS, date + '.log'), 'a') as fh:
                fh.write('{0} {1} {2}\n'.format(time, nickg, message))
        else:
            with open(os.path.join(cd, date + '.log'), 'a') as fh:
                fh.write('{0} {1} {2}\n'.format(time, nickg, message))

    def noticed(self, user, channel, message):
        nick, _, host = user.partition('!')
        if (not self.identified and nick.lower() == 'nickserv' and
                'identified' in message):
            self.identified = True
            for net, ch in self.factory.channels:
                if net == self.network:
                    self.join(ch)
        if channel != '*':
            self._logmsg(channel, nick, message, notice=True)

    def action(self, user, channel, message):
        nick, _, host = user.partition('!')
        self._logmsg(channel, nick, message, action=True)

    def privmsg(self, user, channel, message):
        nick, _, host = user.partition('!')
        self._logmsg(channel, nick, message)
        message = message.strip()
        m = CMDR.match(message)
        if not m:
            return

        _, command, args = m.groups()
        args = (args or '').strip()
        # Get the function corresponding to the command given.
        func = getattr(self, 'command_' + command, None)
        if func is None:
            # Try to get a factoid.
            func = self.command_factoid
            args = (command, args)
        # maybeDeferred will always return a Deferred. It calls func(rest), and
        # if that returned a Deferred, return that. Otherwise, return the
        # return value of the function wrapped in
        d = defer.maybeDeferred(func, nick, args, channel)
        d.addErrback(self._showError)
        d.addCallback(self._sendMessage, channel, nick)

    def _sendMessage(self, msg, target, nick=None):
        if msg is None:
            return
        if nick:
            msg = '%s: %s' % (nick, msg)
        self.msg(target, msg)
        self._logmsg(target, self.nickname, msg)

    def _showError(self, failure):
        return failure.getErrorMessage()

    def command_ping(self, *args):
        return 'pong'

    def command_help(self, *args):
        return 'This is KwBot. https://chriswarrick.com/kwbot/'

    def command_clear(self, originator, args, channel):
        if originator != ADMIN:
            return 'Error: must be admin to clear tell queue.'

        self.toBeDelivered = {}
        return 'Tell queue cleared successfully.'

    def command_hello(self, *args):
        return 'Hello!'

    def command_hi(self, *args):
        return 'Hi!'

    def load_factoids(self):
        with open(CONFHOME + "/factoids.json", encoding="utf-8") as fh:
            factoids = json.load(fh)
        self.factoids = {}
        self.fcount = 0
        for channel, chf in factoids.items():
            chanfactoids = {}
            for k, v in chf.items():
                chanfactoids[k] = v
                self.fcount += 1
            self.factoids[channel] = chanfactoids
        log.msg("{0} factoids loaded".format(self.fcount))
        return self.fcount

    def command_factoid(self, nick, args, channel):
        factoid, args = args
        out = None
        # Try to get channel first.
        chf = self.factoids.get(channel)
        if chf is not None:
            out = chf.get(factoid)

        # Try globals next.
        if out is None:
            out = self.factoids["!global"].get(factoid)

        return out

    def command_factoids(self, nick, args, channel):
        return channel + " factoids: " + ', '.join(sorted(self.factoids[channel]))

    def command_tell(self, originator, args, channel):
        target, msg = args.split(' ', 1)
        time = datetime.datetime.utcnow().strftime('%H:%M:%S')
        if channel not in self.toBeDelivered:
            self.toBeDelivered[channel] = {}
        if target not in self.toBeDelivered[channel]:
            self.toBeDelivered[channel][target] = []
        self.toBeDelivered[channel][target].append([time, originator, msg])
        return 'acknowledged.'

    def command_logs(self, originator, args, channel):
        if channel == '#nikola':
            return 'Logs for #nikola: https://irclogs.getnikola.com/'
        else:
            return 'This channel is logged, but the logs are not available publicly yet. Channel operators can ask for publication.'

    def command_rehash(self, originator, args, channel):
        if originator != ADMIN:
            return "Error: must be admin to rehash."
        GHIssuesResource.tokenmap = {}
        GHIssuesResource.load_tokenmap()

        self.load_factoids()

        return "{0} tokens and {1} factoids loaded.".format(
            len(GHIssuesResource.tokenmap),
            self.fcount)

    def _sendTells(self, target, channel):
        d = self.toBeDelivered.get(channel, {}).pop(target, [])
        for i in d:
            msg = '{0} <{1}> {2}'.format(*i)
            self._sendMessage(msg, channel, target)

    def userJoined(self, target, channel):
        self._sendTells(target, channel)

    def irc_NICK(self, prefix, params):
        """Called when an IRC user changes their nickname."""
        old_nick = prefix.split('!')[0]
        new_nick = params[0]
        for channel in self.toBeDelivered:
            self._sendTells(old_nick, channel)
            self._sendTells(new_nick, channel)

    def irc_unknown(self, prefix, command, params):
        """Handle an unknown command."""
        if command == "INVITE":
            log.msg("invited to " + params[1])
            self.join(params[1])


class KwBotIRCFactory(protocol.ReconnectingClientFactory):
    protocol = KwBotIRCProtocol
    channels = CHANNELS


class GHIssuesResource(resource.Resource):
    isLeaf = True
    repomap = {}
    tokenmap = {}

    def __init__(self):
        resource.Resource.__init__(self)
        self.load_tokenmap()

    @staticmethod
    def load_tokenmap():
        GHIssuesResource.tokenmap = {}
        for src, dest in (
                ('/repomap.csv', GHIssuesResource.repomap),
                ('/tokenmap.csv', GHIssuesResource.tokenmap)
        ):
            with open(CONFHOME + src) as fh:
                for l in fh:
                    k, v = l.split(',')
                    dest[k] = v.strip()

        log.msg("GHIssues: {0} tokens loaded".format(len(GHIssuesResource.tokenmap)))

    def render_GET(self, request):
        request.setHeader("content-type", "text/plain")
        request.setResponseCode(400)
        log.msg('GHIssues: GET {0} {1}'.format(request.uri, request.client))
        return 'does not compute'

    def render_POST(self, request):
        request.setHeader("content-type", "text/plain")
        log.msg('GHIssues: POST {0} {1}'.format(request.uri, request.client))

        d = request.content.getvalue()
        data = json.loads(d)
        event = request.getHeader('X-Github-Event')
        if event == 'ping':
            log.msg('GHIssues: PING {0}'.format(data['hook']))
            request.setResponseCode(200)
            return b'pong'
        elif event not in ('issues', 'pull_request'):
            request.setResponseCode(400)
            log.msg('GHIssues: wtf event')
            return b'wtf event'
        is_issue = event == 'issues'
        evkey = 'issue' if is_issue else 'pull_request'
        try:
            info = {
                'type': 'issue' if is_issue else 'pull request',
                'repo': data['repository']['name'],
                'actor': data['sender']['login'],
                'action': data['action'],
                'number': data[evkey]['number'],
                'title': data[evkey]['title'],
                'url': data[evkey]['html_url'],
            }
            if not is_issue:
                info['head'] = data[evkey]['head']['label']
        except KeyError:
            request.setResponseCode(400)
            log.msg('GHIssues: wtf info')
            return b'wtf info'

        repo_full = data['repository']['full_name']

        sig = request.getHeader('X-Hub-Signature')
        mac = hmac.new(self.tokenmap[repo_full].encode('latin1'), msg=d, digestmod=hashlib.sha1)
        if hmac.compare_digest('sha1=' + mac.hexdigest(), sig) is False:
            request.setResponseCode(400)
            log.msg('GHIssues: wtf signature')
            return b'wtf signature'

        if repo_full not in self.repomap:
            request.setResponseCode(400)
            log.msg('GHIssues: wtf unauthorized')
            return b'wtf unauthorized'
        else:
            channel = self.repomap[repo_full]

        message = None
        if info['action'] in ['opened', 'closed', 'reopened', 'unassigned']:
            message = GHISSUES_TXT if is_issue else GHISSUES_PR
        elif info['action'] == 'assigned':
            info['assignee'] = data['assignee']['login']
            message = GHISSUES_ASSIGN if is_issue else GHISSUES_ASSIGN_PR
            for b in BOT:
                b._sendMessage(GHISSUES_ASSIGN.format(**info), channel)

        elif info['action'] in ('review_requested', 'review_request_removed'):
            info['reviewer'] = data['requested_reviewer']['login']
            message = GHISSUES_REVIEW if info['action'] == 'review_requested' else GHISSUES_UNREVIEW

        if not message:
            request.setResponseCode(200)
            log.msg('GHIssues: wtf action (200)')
            return b'wtf action'

        for b in BOT:
            b._sendMessage(message.format(**info), channel)
        request.setResponseCode(200)
        return b'ack'

if __name__ == '__main__':
    log.startLogging(sys.stderr)
    log.startLogging(open(os.path.join(LOGDIR, 'KwBot.log'), 'a'))
    ircf = KwBotIRCFactory()
    #reactor.connectTCP("chat.freenode.net", 6667, ircf)
    reactor.connectSSL("irc.libera.chat", 6697, ircf, ssl.ClientContextFactory())
    reactor.listenTCP(5944, server.Site(GHIssuesResource()))
    reactor.run()
