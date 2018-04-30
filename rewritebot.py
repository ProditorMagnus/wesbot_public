#!/usr/bin/python3.6
import logging
import logging.handlers

import sys
import os

from rewritebotCFG import WesSettings
from rewritebotCMD import CommandHandler
from rewritebotIRC import WesIrc
from rewritebotCON import WesSock
from rewritebotACT import Actor
from rewritebotSCHEMA import *


class WesBot:
    irc: WesIrc
    commandHandler: CommandHandler
    wesSock: WesSock
    actor: Actor

    def __init__(self):
        self.cfg = WesSettings
        self.wesSock = None
        self.irc = None
        self.signal_actions = set()
        # TODO gameholder+userholder to lobbyholder to see who is in what game
        self.games: GameHolder = GameHolder(self)
        self.users = UserHolder(self)
        self.log = logging.getLogger("general")
        fh = logging.handlers.RotatingFileHandler("log/general.log", maxBytes=10 * 1024 * 1024, backupCount=2)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        self.log.setLevel(logging.DEBUG)
        self.log.addHandler(fh)
        self.commandHandler = CommandHandler(self, self.cfg.botMasterNames[:], self.cfg.botMasterNames[:])
        self.actor = Actor(self)

    def handleWesResponse(self):
        response = self.wesSock.receive_string()
        if len(response) == 0:
            return
        self.actor.actOnWML(self.actor.parseWML(response))

    def main(self):
        cfg = self.cfg
        self.quitIfDisabled()
        try:
            if cfg.ircEnabled and not self.irc:
                self.log.info("irc is enabled")
                self.irc = WesIrc(self)
                self.irc.connect()
            if cfg.wesEnabled and not self.wesSock:
                self.log.info("wes is enabled")
                self.wesSock = WesSock(self, cfg.wesnothVersion)
                self.wesSock.connect(cfg.serverName)
                reconnect_attempts = 3
                for i in range(reconnect_attempts):
                    if self.wesSock.loginLobby(cfg.username, cfg.password):
                        self.log.info("Managed to join lobby")
                        self.handleWesResponse()
                        break
                    else:
                        self.log.warning("Failed to join lobby, trying again")
                    if i == reconnect_attempts - 1:
                        raise WesException("Did not manage to join lobby").addAction(WesException.FATAL)

            self.mainLoop()
        except WesException as e:
            self.log.error(e.__str__())
            self.log.debug("actions %s", e.action)
            for act in e.action:
                if act == WesException.RESTART:
                    self.signal_actions.add(WesException.QUIT)
                elif act == WesException.FATAL:
                    self.signal_actions.add(WesException.QUIT)
                    self.log.error("Fatal error")
                self.signal_actions.add(act)

            self.log.exception(e)
        except Exception as e:
            self.log.error("generic error")
            self.log.exception(e)
            self.signal_actions.add(WesException.QUIT)
        finally:
            if WesException.QUIT_IRC in self.signal_actions:
                self.cleanupIrc()
                cfg.ircEnabled = False
            if WesException.QUIT_WES in self.signal_actions:
                self.cleanupWes()
                cfg.wesEnabled = False
            if WesException.RESTART in self.signal_actions:
                # os.execv(__file__, sys.argv)
                # os.execl(sys.executable,sys.executable,* sys.argv)
                self.log.info("attempting to restart")
                os.execl(sys.executable, os.path.abspath(__file__), *sys.argv)
            if WesException.QUIT in self.signal_actions:
                self.cleanup()
                sys.exit(0)
            if WesException.RECONNECT_IRC in self.signal_actions:
                self.cleanupIrc()
                cfg.ircEnabled = True
            if WesException.RECONNECT_WES in self.signal_actions:
                self.cleanupWes()
                cfg.wesEnabled = True

            # Since we did not restart or quit, go back to mainloop
            self.main()

    def mainLoop(self):
        cfg = self.cfg
        self.commandHandler.init()
        while True:
            if cfg.ircEnabled:
                irc_response = self.irc.receive()
                irc_parts = irc_response.split(" ", 3)  # TODO might break when multiple commands are in same packet
                if len(irc_parts) > 2 and irc_parts[1] == "PRIVMSG":
                    self.commandHandler.onIrcMessage(irc_response.strip())
            if cfg.wesEnabled:
                self.handleWesResponse()
            self.quitIfDisabled()

    def quitIfDisabled(self):
        cfg = self.cfg
        if not cfg.ircEnabled and not cfg.wesEnabled:
            self.log.error("Neither irc not wesnoth is enabled, there is nothing to do")
            raise WesException().quit()

    def cleanup(self):
        self.cleanupWes()
        self.cleanupIrc()

    def cleanupWes(self):
        if self.wesSock:
            self.wesSock.shutdown()
            self.wesSock = None

    def cleanupIrc(self):
        if self.irc:
            self.irc.shutdown()
            self.irc = None


if __name__ == "__main__":
    WesBot().main()
