#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# KwBot
# A simple, opinionated Python/Twisted bot.
# INSERT TAGLINE HERE.
# Copyright © 2015, Chris Warrick.
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
LOGDIR = '/home/kwpolska/virtualenvs/kwbot/logs'
NIKOLOGS = '/home/kwpolska/nikola-logs/logs'
LOGHANDLES = {}
import datetime
import sys
import os
import re

from time import sleep
from twisted.internet import defer, endpoints, protocol, task
from twisted.python import log
from twisted.words.protocols import irc

R = re.compile('(KwBot.? |!)(?P<command>[a-z]+)(?P<args> .*)?', re.U | re.I)


class KwBotIRCProtocol(irc.IRCClient):
    nickname = 'KwBot'
    realname = 'Chris Warrick’s Friendly Bot'
    versionName = 'KwBot'

    def __init__(self):
        self.deferred = defer.Deferred()
        self.toBeDelivered = {}

    def connectionLost(self, reason):
        self.deferred.errback(reason)

    def signedOn(self):
        with open('/home/kwpolska/kwbot-password') as fh:
            NICKSERV_PWD = fh.read().strip()
        self.msg('NickServ', 'identify KwBot {0}'.format(NICKSERV_PWD))
        sleep(2)
        for channel in self.factory.channels:
            self.join(channel)

    def joined(self, channel):
        log.msg('joined ' + channel)
        if channel != '#nikola':
            LOGHANDLES[channel] = open(os.path.join(LOGDIR, channel + '.log'), 'a')

    def _logmsg(self, channel, nick, message, notice=True):
        """Log a message."""
        dt = datetime.datetime.utcnow()
        date = dt.strftime('%Y-%m-%d')
        time = dt.strftime('%H:%M:%S')
        full = dt.strftime('%Y-%m-%d %H:%M:%S')
        if notice:
            nickg = '-{0}:{1}-'.format(nick, channel)
        else:
            nickg = '<{0}>'.format(nick)
        if channel == '#nikola':
            with open(os.path.join(NIKOLOGS, date + '.log'), 'a') as fh:
                fh.write('{0} {1} {2}\n'.format(time, nickg, message))
        else:
            LOGHANDLES[channel].write('{0} {1} {2}\n'.format(full, nickg, message))
            LOGHANDLES[channel].flush()

    def noticed(self,user, channel, message):
        nick, _, host = user.partition('!')
        self._logmsg(channel, nick, message, notice=True)

    def privmsg(self, user, channel, message):
        nick, _, host = user.partition('!')
        self._logmsg(channel, nick, message)
        message = message.strip()
        m = R.match(message)
        if not m:
            return

        _, command, args = m.groups()
        args = (args or '').strip()
        # Get the function corresponding to the command given.
        func = getattr(self, 'command_' + command, None)
        # Or, if there was no function, ignore the message.
        if func is None:
            return
        # maybeDeferred will always return a Deferred. It calls func(rest), and
        # if that returned a Deferred, return that. Otherwise, return the
        # return value of the function wrapped in
        d = defer.maybeDeferred(func, nick, args, channel)
        d.addErrback(self._showError)
        d.addCallback(self._sendMessage, channel, nick)

    def _sendMessage(self, msg, target, nick=None):
        if nick:
            msg = '%s: %s' % (nick, msg)
        self.msg(target, msg)
        self._logmsg(target, self.nickname, msg)

    def _showError(self, failure):
        return failure.getErrorMessage()

    def command_ping(self, *args):
        return 'pong'

    def command_help(self, *args):
        return 'This is KwBot.  Read more: https://chriswarrick.com/kwbot/'

    def command_clear(self, originator, args, channel):
        if originator != 'ChrisWarrick':
            return 'Error: must be ChrisWarrick to clear tell queue.'
        else:
            self.toBeDelivered = {}
            return 'tell queue cleared successfully.'

    def command_hello(self, *args):
        return 'Hello!'

    def command_hi(self, *args):
        return 'Hi!'

    def command_tell(self, originator, args, channel):
        target, msg = args.split(' ', 1)
        time = datetime.datetime.utcnow().strftime('%H:%M:%S')
        if channel not in self.toBeDelivered:
            self.toBeDelivered[channel] = {}
        if target not in self.toBeDelivered[channel]:
            self.toBeDelivered[channel][target] = []
        self.toBeDelivered[channel][target].append([time, originator, msg])
        return 'acknowledged.'


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
    channels = ['#nikola', '##kwbot']


def main(reactor, description):
    endpoint = endpoints.clientFromString(reactor, description)
    factory = KwBotIRCFactory()
    d = endpoint.connect(factory)
    d.addCallback(lambda protocol: protocol.deferred)
    return d


if __name__ == '__main__':
    log.startLogging(sys.stderr)
    task.react(main, ['tcp:irc.freenode.net:6667'])
