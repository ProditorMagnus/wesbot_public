# from __future__ import annotations # TODO 3.7+
from typing import List, Dict, Any, Union

import wmlparser
import typing

if typing.TYPE_CHECKING:
    from rewritebot import WesBot


class WesException(Exception):
    ASSERT = "assert"
    FATAL = "fatal"
    QUIT = "quit"
    QUIT_WES = "quit_wes"
    QUIT_IRC = "quit_irc"
    RESTART = "restart"
    RECONNECT_IRC = "ircreconnect"
    RECONNECT_WES = "wesreconnect"

    def __init__(self, value=""):
        self.value = value
        self.action = []

    def __str__(self):
        return "WesException({0}, {1})".format(repr(self.value), repr(self.action))

    def quit(self):
        return self.addAction(WesException.QUIT)

    def restart(self):
        return self.addAction(WesException.RESTART)

    def reconnectIrc(self):
        return self.addAction(WesException.RECONNECT_IRC)

    def reconnectWes(self):
        return self.addAction(WesException.RECONNECT_WES)

    def addAction(self, action):
        self.action.append(action)
        return self

    @staticmethod
    def ensure(condition: bool, message: str = ""):
        if not condition:
            raise WesException(message).addAction(WesException.ASSERT)


class Game:
    def __init__(self, node: wmlparser.TagNode):
        self.node = node
        self.id = node.get_text_val("id")
        self.name = node.get_text_val("name")
        self.mp_scenario = node.get_text_val("mp_scenario")
        self.mp_era = node.get_text_val("mp_era")
        self.mp_use_map_settings = node.get_text_val("mp_use_map_settings")
        self.observer = node.get_text_val("observer") == "yes"
        # self.human_sides = node.get_text_val("human_sides") # TODO find why I had human_sides there
        # TODO use [slot_data], [slot_data]\nmax="2"\nvacant="0"\n[/slot_data]
        self.users = []

    def debug(self):
        # return "Game: %s: %s" % (self.id, self.name)
        return self.node.debug()

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return "Game({}={})".format(self.id, self.name)


class GameHolder:
    games: List[Game]
    gameMap: Dict[int, Game]  # game id -> game

    def __init__(self, main: 'WesBot'):
        self.main = main
        self.games = []
        self.gameMap = {}

    def addInitialGame(self, g: Game):
        self.games.append(g)
        self.gameMap[g.id] = g
        self.main.log.info("Saved initial game %s(%s) to last index %s", g.name, g.id, len(self.games) - 1)

    def removeGame(self, index):
        WesException.ensure(len(self.games) > index)
        pop: Game = self.games.pop(index)
        WesException.ensure(pop.id in self.gameMap,
                            "GameMap {} Must have entry of {}, even when not removing"
                            .format(str(self.gameMap), pop.id))
        # del self.gameMap[pop.id] # cant remove, since insert is processed before remove, it ends up without entry
        self.main.log.info("Deleted game %s(%s) from index %s", pop.name, pop.id, index)

    def getGames(self):
        return self.games

    def insertGame(self, g: Game, index):
        self.games.insert(index, g)
        self.gameMap[g.id] = g
        self.main.log.info("Saved game %s(%s) to index %s", g.name, g.id, index)


# http://devdocs.wesnoth.org/server_8cpp_source.html#l00178
# //inserts will be processed first by the client, so insert at index+1,
# //and then when the delete is processed we'll slide into the right position

class User:
    def __init__(self, node: wmlparser.TagNode):
        self.node = node
        self.available = node.get_text_val("available")
        self.game_id = node.get_text_val("game_id")
        self.location = node.get_text_val("location")
        self.name = node.get_text_val("name")
        self.registered = node.get_text_val("registered") == "yes"
        self.status = node.get_text_val("status")
        self.online = None

    def debug(self):
        # return "User(" + self.name + ", registered=" + str(self.registered) + ")"
        return self.node.debug()

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return "User({})".format(self.name)


class UserHolder:
    def __init__(self, main: 'WesBot'):
        self.main = main
        self._users = {}  # name -> user
        self._usersList = []  # index -> name

    def add(self, user: User):
        user.online = True
        self._users[user.name] = user
        self._usersList.append(user.name)

    def addIfAbsent(self, user):
        if user.name in self._users:
            # print("user",user.name,"is already in userholder")
            return
        self.add(user)

    def insertUser(self, user, index):
        self._usersList.insert(index, user.name)
        self._users[user.name] = user

    def getI(self, index):
        WesException.ensure(len(self._usersList) > index,
                            "User list {} has no index {}".format(str(self._usersList), index))
        return self._users.get(self._usersList[index])

    def get(self, name):
        WesException.ensure(name in self._users, str(self._users))
        return self._users.get(name)

    def deleteI(self, index):
        WesException.ensure(len(self._usersList) > index,
                            "User list {} has no index {}".format(str(self._usersList), index))
        self._usersList.pop(index)

    def delete(self, name):
        self.main.log.warn("maybe this function delete in UserHolder should never be used")
        WesException.ensure(name in self._users, str(self._users))
        del self._users[name]

    def isRegistered(self, name):
        if name not in self._users:
            return False
        return self._users[name].registered

    def printUsers(self):
        self.main.log.info("shared users", self._users, self._usersList)

    def getOnlineUsers(self) -> Dict[str, User]:
        onlineUsers = {}
        for name in self._usersList:
            onlineUsers[name] = self._users[name]
        return onlineUsers

    def getUsers(self) -> Dict[str, User]:
        users = {}
        for name in self._users:
            users[name] = self._users[name]
        return users
