# from __future__ import annotations # TODO 3.7+
import json
import os
from collections.__init__ import defaultdict
from datetime import datetime
from typing import List, Dict
import time
import datetime
from weakreflist import WeakList

import wmlparser
import typing

if typing.TYPE_CHECKING:
    from rewritebot import WesBot
    from logging import Logger


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
    def ensure(condition: bool, message: str = "", reconnect=False):
        if not condition:
            if reconnect:
                raise WesException(message).addAction(WesException.ASSERT).reconnectWes()
            else:
                raise WesException(message).addAction(WesException.ASSERT).quit()


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
    _gameList: List[Game]
    _gameMap: Dict[int, Game]  # game id -> game # TODO check if this gets too large and needs to be cleared

    def __init__(self, main: 'WesBot', lobby: 'LobbyHolder'):
        self.lobby = lobby
        self.main = main
        self._gameList = []
        self._gameMap = {}
        self.main.gameLog.info("Initialized GameHolder")

    def addInitialGame(self, g: Game):
        self._gameList.append(g)
        self._gameMap[g.id] = g
        self.main.gameLog.info("Saved initial game %s(%s) to last index %s", g.name, g.id, len(self._gameList) - 1)

    def removeGame(self, index):
        self.main.gameLog.debug("Deleting game from index %s", index)
        WesException.ensure(len(self._gameList) > index)
        pop: Game = self._gameList.pop(index)
        WesException.ensure(pop.id in self._gameMap,
                            "GameMap {} Must have entry of {}, even when not removing"
                            .format(str(self._gameMap), pop.id))
        # del self.gameMap[pop.id] # cant remove, since insert is processed before remove, it ends up without entry
        self.main.gameLog.info("Deleted game %s(%s) from index %s", pop.name, pop.id, index)

    def getGames(self):
        return self._gameList

    def insertGame(self, g: Game, index):
        WesException.ensure(index <= len(self._gameList),
                            "index ({}) <= len(self._gameList) ({})".format(index, len(self._gameList)))
        self._gameList.insert(index, g)
        self._gameMap[g.id] = g
        self.main.gameLog.info("Saved game %s(%s) to index %s", g.name, g.id, index)

    def reset(self):
        self._gameList.clear()
        self.main.gameLog.info("Cleared games list")

    def getStats(self):
        return "Current games: {}, Seen games: {}".format(len(self._gameList), len(self._gameMap))


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

    def debug(self):
        # return "User(" + self.name + ", registered=" + str(self.registered) + ")"
        return self.node.debug()

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return "User({})".format(self.name)


class UserHolder:
    _users: Dict[str, User]
    _userList: List[User]

    def __init__(self, main: 'WesBot', lobby: 'LobbyHolder'):
        self.lobby = lobby
        self.main = main
        self._users = {}  # name -> user
        self._userList = []  # index -> user
        self.main.userLog.info("Initialized UserHolder")

    def addInitialUser(self, user: User):
        self._users[user.name] = user
        self._userList.append(user)
        self.main.userLog.info("Saved initial user %s to last index %s", user.name, len(self._userList) - 1)
        self.lobby.stats.onUserAdd(user.name, "Initial")

    def insertUser(self, user: User, index, comment=""):
        self.main.userLog.debug("Saving user %s to index %s, current last index %s", user.name, index,
                                len(self._userList) - 1)
        WesException.ensure(index <= len(self._userList),
                            "index ({}) <= len(self._userList) ({})".format(index, len(self._userList)))
        self._userList.insert(index, user)
        self._users[user.name] = user
        self.lobby.stats.onUserAdd(user.name, comment)
        self.main.userLog.info("Saved user %s to index %s, current last index %s", user.name, index,
                               len(self._userList) - 1)

    def getI(self, index: int) -> User:
        WesException.ensure(len(self._userList) > index, "User list {} has no index {}"
                            .format(str(self._userList), index))
        return self._userList[index]

    def get(self, name: str) -> User:
        name = name.strip()
        WesException.ensure(name in self._users, str(self._users))
        return self._users.get(name)

    def deleteI(self, index, comment=""):
        self.main.userLog.debug("Deleting user from index %s, current last index %s", index, len(self._userList) - 1)
        WesException.ensure(len(self._userList) > index, "User list {} with len {} has no index {}"
                            .format(str(self._userList),
                                    len(self._userList), index))
        u: User = self._userList.pop(index)
        self.lobby.stats.onUserRemove(u.name, comment)
        self.main.userLog.info("Deleted user %s from index %s, current last index %s", u.name, index,
                               len(self._userList) - 1)

    def isRegistered(self, name: str) -> bool:
        name = name.strip()
        if name not in self._users:
            return False
        return self._users[name].registered

    def getOnlineUsers(self) -> List[User]:
        return self._userList

    def getOnlineNames(self) -> List[str]:
        return list(map(lambda u: u.name, self._userList))

    def getUsers(self) -> Dict[str, User]:
        return self._users

    def reset(self):
        self._userList.clear()
        self.main.userLog.info("Cleared userList")

    def getStats(self):
        # TODO keep stats as separate int, so that removing old data doesnt break stats, separate stats file even
        return "Current users: {}, Seen users: {}".format(len(self._userList), len(self._users))


class UserEvent:
    time: float
    event: str
    name: str
    comment: str

    def __init__(self, timestamp, event, name, comment=""):
        self.time = timestamp
        self.event = event
        self.name = name
        self.comment = comment

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)

    @staticmethod
    def fromJSON(JSON: str):
        e = json.loads(JSON)
        return UserEvent(e["time"], e["event"], e["name"], e["comment"])


class StatsHolder:
    log: 'Logger'
    lastUpdate: datetime
    # user and game events:
    # User logs in
    # User logs out
    # User join game
    # User leaves game
    connectTimes: List[float] = [0]
    userEvents = WeakList()
    userEventsView: Dict[str, List[UserEvent]] = defaultdict(list)

    def __init__(self, main: 'WesBot', log) -> None:
        self.main = main
        self.log = log
        self.lastUpdate = datetime.datetime.now()

    def addConnectTime(self) -> None:
        if self.connectTimes[0] < 0.0001:
            self.connectTimes.clear()
        self.connectTimes.append(time.time())

    def getTimeSinceFirstConnect(self) -> str:
        return str(datetime.timedelta(seconds=time.time() - self.connectTimes[0]))

    def getTimeSinceLastConnect(self):
        return str(datetime.timedelta(seconds=time.time() - self.connectTimes[-1]))

    def onUserRemove(self, name, comment=""):
        if comment is None:
            return
        e = UserEvent(time.time(), "-", name, comment)
        self.userEventsView[name].append(e)
        self.userEvents.append(e)

    def onUserAdd(self, name, comment=""):
        if comment is None:
            return
        e = UserEvent(time.time(), "+", name, comment)
        self.userEventsView[name].append(e)
        self.userEvents.append(e)

    def getUserStats(self, name: str) -> str:
        name = name.strip()
        self.loadUserEvents(name)
        if name not in self.userEventsView:
            return "No stats found for '{}'".format(name)
        d = self.userEventsView[name]
        totalUptime = 0
        lastUptime = 0
        firstJoin = 0
        latestJoin = 0
        lastSeen = 0
        count = 0
        # 0 -> user is offline
        # 1 -> user is online
        # 2 -> user is added, and immediately deleted
        for e in d:
            if e.event == "+":
                count += 1
                if count == 2:
                    continue
                if firstJoin == 0:
                    firstJoin = e.time
                if count == 1:
                    latestJoin = e.time
            if e.event == "-":
                count -= 1
                if e.comment == "onQuit":  # Everyone is considered offline while bot is offline
                    count = 0
                if count == 1:
                    continue
                if count == 0:
                    lastUptime = e.time - latestJoin
                    totalUptime += lastUptime
                    lastSeen = e.time
        if count == 1:
            lastSeen = time.time()
            lastUptime = lastSeen - latestJoin
            totalUptime += lastUptime
        return "{} has been online for {}, in last session {}. Last seen online: {}".format(
            name, str(datetime.timedelta(seconds=totalUptime)), str(datetime.timedelta(seconds=lastUptime)),
            datetime.datetime.fromtimestamp(lastSeen).strftime('%d.%m %H:%M:%S'))

    def getLastSeenTime(self, name: str) -> datetime:
        lastSeen = 0
        name = name.strip()
        if name not in self.userEventsView:
            self.log.debug("No stats for user {}".format(name))
            return datetime.datetime.fromtimestamp(lastSeen)
        d = self.userEventsView[name]
        # TODO save user updates with different comment than login and logout
        # Last event time, and for online users current time
        if len(d) > 0:
            lastSeen = d[-1].time
        if name in self.main.lobby.users.getOnlineNames():
            lastSeen = time.time()
        fromtimestamp = datetime.datetime.fromtimestamp(lastSeen)
        self.log.log(4, "Found last seen time {} for {}".format(fromtimestamp, name))
        return fromtimestamp

    def onQuit(self):
        self.log.debug("Removing all online users on quit")
        self.logStats()
        u: User
        for u in self.main.lobby.users.getOnlineUsers():
            self.onUserRemove(u.name, "onQuit")
        self.saveUsers()

    def tick(self):
        now: datetime = datetime.datetime.now()
        if now - self.lastUpdate > datetime.timedelta(hours=1):
            self.logStats()
            self.deleteOldData(now)
            self.lastUpdate = now

    def logStats(self):
        self.log.info("Game stats: {}, User stats: {}".format(self.main.lobby.games.getStats(),
                                                              self.main.lobby.users.getStats()))

    def deleteOldData(self, now: datetime, deletionTime: datetime.timedelta = datetime.timedelta(hours=2)):
        self.log.debug("userEvents count before archive {}".format(len(self.userEvents)))

        self.saveUsers()
        deletableNames = set()
        for name in self.userEventsView:
            last_seen_time: datetime = self.getLastSeenTime(name)
            time_since_seen: datetime.timedelta = now - last_seen_time
            self.log.log(5, "User {} time since seen {}, time seen {}".format(name, time_since_seen, last_seen_time))
            if time_since_seen > deletionTime:
                deletableNames.add(name)
        for name in deletableNames:
            del self.userEventsView[name]
            self.log.debug("Deleted {}".format(name))
        self.log.debug("userEvents count after archive {}".format(len(self.userEvents)))

    def saveUsers(self):
        for name in self.userEventsView:
            unsavedSince = 0

            filename = "user_events/{}/{}.log".format(name, name)
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            if os.path.isfile(filename):
                with open(filename, "r", encoding="utf8") as f:
                    lines = f.readlines()
                    if len(lines) > 0:
                        e = UserEvent.fromJSON(lines[-1])
                        unsavedSince = e.time

            with open(filename, "a", encoding="utf8") as f:
                for e in self.userEventsView[name]:
                    if e.time > unsavedSince + 0.0001:
                        f.write(e.toJSON() + "\n")
            # TODO new file when it is too large
            # if os.path.getsize(filename) > 1 * 1000 * 1000:
            #     pass
        self.main.log.debug("Users saved")

    def loadUserEvents(self, name):
        filename = "user_events/{}/{}.log".format(name, name)
        if not os.path.isfile(filename):
            return
        self.log.debug("Loading user events for {}".format(name))
        loadedEvents = []
        firstAvailableTime = time.time()
        if len(self.userEventsView[name]) > 0:
            firstAvailableTime = self.userEventsView[name][0].time
        with open(filename, "r", encoding="utf8") as f:
            for line in f:
                e = UserEvent.fromJSON(line)
                if e.time < firstAvailableTime:
                    loadedEvents.append(e)
        self.log.debug("Loaded {} user events for {}".format(len(loadedEvents), name))
        if len(loadedEvents) == 0:
            return
        self.userEventsView[name].extend(loadedEvents)
        self.log.debug("First extend")
        self.userEventsView[name].sort(key=lambda e: e.time)
        self.log.debug("First sort")
        self.userEvents.extend(loadedEvents)
        self.log.debug("Second extend")
        self.userEvents.sort(key=lambda e: e.time)
        self.log.debug("Second sort")


class LobbyHolder:
    users: UserHolder
    games: GameHolder
    stats: StatsHolder

    def __init__(self, main: 'WesBot', statsLog: 'Logger'):
        self.main = main
        self.users = UserHolder(main, self)
        self.games = GameHolder(main, self)
        self.stats = StatsHolder(main, statsLog)

    def reset(self):
        self.stats.onQuit()
        self.users.reset()
        self.games.reset()
