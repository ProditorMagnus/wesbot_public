from typing import List

import wmlparser
import typing

if typing.TYPE_CHECKING:
    from rewritebot import WesBot
from rewritebotSCHEMA import User, Game, WesException

# TODO handle b'[message]\nmessage="Can\'t find \'Ravana\'."\nsender="server"\n[/message]\n'        about ping

# like helper methods to get all tags with given path, or attributes
# https://wiki.wesnoth.org/MultiplayerServerWML

class Actor:
    def __init__(self, main: 'WesBot'):
        self.log_cutoff_len = 500
        self.main = main
        self.cmd = main.commandHandler
        self.parser = wmlparser.Parser(None)

    def parseWML(self, s):
        if len(s) == 0:
            return s
        wml = self.parser.parse_text(s)
        # if len(s) < self.log_cutoff_len:
        #     self.main.log.debug("WML %s", wml.debug())
        return wml

    def actOnWML(self, wml, path=None):
        if path is None:
            path = []
        if (type(wml) is wmlparser.TagNode) or (type(wml) is wmlparser.RootNode):
            attr: List[wmlparser.AttributeNode] = []
            attrPath = path[:]
            for node in wml.get_all():
                if type(node) is wmlparser.AttributeNode:
                    attr.append(node)
                else:
                    self.main.log.log(2, "got node %s", node.get_name())
                    if node.get_name() == "gamelist_diff":
                        self.actOnGamelistDiff(node)
                    elif node.get_name() == "user":
                        self.actOnUser(node)
                    elif node.get_name() == "gamelist":
                        self.actOnGamelist(node)
                    elif node.get_name() == "whisper":
                        self.actOnWhisper(node)
                    elif node.get_name() == "message":
                        # TODO only use relevant messages, not those in scenario code
                        self.actOnMessage(node)
                    elif node.get_name() == "speak":
                        self.actOnSpeak(node)
                    elif node.get_name() == "error":
                        self.actOnError(node)
                    elif node.get_name() == "observer":
                        self.actOnObserver(node)
                    elif node.get_name() == "observer_quit":
                        self.actOnObserverQuit(node)
                    else:
                        for sub in node.get_all():
                            self.actOnWML(sub, path + [node.get_name()])
            self.parseAttr(attr, attrPath)
        elif type(wml) is list:
            raise WesException("actOnWML got wml as list")
            # attr = []
            # attrPath = path[:]
            # tags = []
            # for node in wml:
            #     if type(node) is wmlparser.AttributeNode:
            #         attr.append(node)
            #     else:
            #         tags.append(node)
            # self.parseAttr(attr, attrPath)
            # for node in tags:
            #     self.actOnWML(node.get_all(), path + [node.get_name()])
        elif type(wml) is wmlparser.AttributeNode:
            self.main.log.log(2, "AttributeNode @%s %s %s", path, wml.get_name(), wml.get_text())

    def actOnGamelistDiff(self, node: wmlparser.TagNode):
        self.main.log.log(2, "in actOnGamelistDiff with %s", node.get_name())
        usersToRemove = set()
        usersToAdd = set()
        for child in node.get_all(tag="delete_child"):
            index = int(child.get_text_val("index"))
            if len(child.get_all(tag="user")) == 1:
                self.main.log.log(5, "user %s should be removed" % index)
                usersToRemove.add(self.main.lobby.users.getI(index).name)

        for child in node.get_all(tag="insert_child"):
            index = int(child.get_text_val("index"))
            self.main.log.log(3, "%s %s", child.get_name(), index)
            for child in child.get_all(tag="user"):
                u = User(child)
                self.main.log.log(5, "user %s should be inserted to %s", u.name, index)
                usersToAdd.add(u.name)
                if u.name in usersToRemove:
                    self.main.lobby.users.insertUser(u, index, None)
                else:
                    self.main.lobby.users.insertUser(u, index)
            for child in child.get_all(tag="game"):
                g = Game(child)
                self.main.log.log(5, "game %s(%s) should be inserted to %s", g.name, g.id, index)
                self.main.lobby.games.insertGame(g, index)

        for child in node.get_all(tag="delete_child"):
            index = int(child.get_text_val("index"))
            self.main.log.log(3, "%s %s", child.get_name(), index)
            if len(child.get_all(tag="user")) == 1:
                self.main.log.log(5, "user %s should be removed" % index)
                if self.main.lobby.users.getI(index).name in usersToAdd:
                    self.main.lobby.users.deleteI(index, None)
                else:
                    self.main.lobby.users.deleteI(index)
            elif len(child.get_all(tag="game")) == 1:
                self.main.log.log(5, "game %s should be removed" % index)
                self.main.lobby.games.removeGame(index)
            else:
                self.main.log.error("actOnGamelistDiff with %s users and %s games",
                                    len(child.get_all(tag="user")),
                                    len(child.get_all(tag="game")))
        for child in node.get_all(tag="change_child"):
            if int(child.get_text_val("index")) != 0:
                raise WesException("[gamelist_diff][change_child]index={}, 0 expected"
                                   .format(node.get_text_val("index")))
            # This has subtags like delete_child, instead of initial uncondition addition
            gamelists = child.get_all(tag="gamelist")
            assert len(gamelists) == 1
            self.actOnGamelistDiff(gamelists[0])

    def actOnUser(self, node: wmlparser.TagNode):
        # self.main.log.error("actOnUser should not be called currently")  # it should, when first joining lobby
        self.main.log.log(2, "on user %s", node.debug())
        # for att in node.get_all(att=""):
        # print("user attr",att.get_name(), att.get_text())

        # maybe should update some stuff?
        # should happen when first connecting
        self.main.lobby.users.addInitialUser(User(node))

        self.main.log.log(2, self.main.lobby.users.get(node.get_text_val("name")))

    def actOnGamelist(self, node: wmlparser.TagNode):
        # when first connecting to lobby
        self.main.log.log(2, "on gamelist")
        # self.main.log.debug("on gamelist %s", node.debug()[:self.log_cutoff_len])
        # save them to games
        for game in node.get_all(tag="game"):
            self.main.lobby.games.addInitialGame(Game(game))

    def actOnWhisper(self, node: wmlparser.TagNode):
        # self.main.log.debug("on whisper %s", node.debug())
        sender = node.get_text_val("sender")
        message = node.get_text_val("message")
        # self.main.log.debug("%s %s %s", sender, "~", message)
        whisper = True
        self.cmd.onWesMessage(message, sender, self.main.lobby.users.isRegistered(sender), whisper)

    def actOnMessage(self, node: wmlparser.TagNode):
        # self.main.log.debug("on message %s", node.debug())
        sender = node.get_text_val("sender")
        message = node.get_text_val("message")
        if sender == "server":
            self.cmd.onServerMessage(message, False)  # TODO is private?
            return
        if not sender or not message:
            self.main.log.error("sender or message is None in actOnMessage")
            return
        # self.main.log.debug("%s %s %s", sender, ">", message)
        self.cmd.onWesMessage(message, sender, self.main.lobby.users.isRegistered(sender))

    def actOnSpeak(self, node: wmlparser.TagNode):
        self.main.log.debug("on speak %s", node.debug())
        sender = node.get_text_val("id")
        message = node.get_text_val("message")
        self.main.log.debug("%s %s %s", sender, ">", message)
        self.cmd.onWesMessage(message, sender, self.main.lobby.users.isRegistered(sender))

    def actOnObserver(self, node: wmlparser.TagNode):
        self.main.log.debug("on observer %s", node.debug())

    def actOnObserverQuit(self, node: wmlparser.TagNode):
        self.main.log.debug("on observer_quit %s", node.debug())

    def actOnError(self, node: wmlparser.TagNode):
        self.main.log.warn("on error %s", node.debug())

    def parseAttr(self, attr: List[wmlparser.AttributeNode], path: List[str]):
        if len(attr) < 1:
            return
        if (len(path) > 0 and (
                path[0] == "era" or path[0] == "music" or
                path[0] == "time" or path[0] == "multiplayer" or path[0] == "event" or path[0] == "side")):
            return
        # input()
        # print("parsing attr")
        for a in attr:
            # TODO test if ping is used anymore, since seems that not
            # if a.get_name() == "ping":
            #     continue
            self.main.log.log(2, "Attr @%s %s=%s", path, a.get_name(), a.get_text())
