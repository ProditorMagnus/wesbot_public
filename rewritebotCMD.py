import datetime
import logging
import logging.handlers
import random
import re
import subprocess
from typing import Dict, Any, Callable

from rewritebotSCHEMA import WesException
import typing

if typing.TYPE_CHECKING:
    from rewritebot import WesBot

PERMISSION_ADMIN = 90
PERMISSION_TRUSTED = 50
PERMISSION_REGISTERED = 10
PERMISSION_PUBLIC = -1


class Command:
    command: Callable  # reply, args, permission, sender

    def __init__(self, permission: int, command: 'Callable',
                 description=""):
        self.command = command
        self.permission = permission
        self.description = description


class CommandHandler:
    pingUsers: Dict[str, typing.Tuple[int, datetime.datetime]]  # name -> (interval, last ping time)
    commands: Dict[str, Command]

    def __init__(self, main: 'WesBot', wesMasters, ircMasters):
        self.commands = {}
        self.prefix = "!"
        self.HELP_MESSAGE = "This is IRC-lobby bot written in Python 3.6 by Ravana. " \
                            "Forum thread: https://forums.wesnoth.org/viewtopic.php?f=10&t=43965. " \
                            "Current prefix: " + self.prefix
        self.main = main
        self.wes = main.wesSock  # TODO useless statement, wesSock is null at that time
        self.irc = main.irc  # TODO useless statement, wesSock is null at that time
        self.wesMasters = wesMasters
        self.ircMasters = ircMasters
        self.log = logging.getLogger("CMD")
        fh = logging.handlers.RotatingFileHandler("log/wesbot_cmd.log", maxBytes=10 * 1024 * 1024, backupCount=2)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        self.log.setLevel(logging.DEBUG)
        self.log.addHandler(fh)
        self.initializeCommands()
        self.pingUsers = {}

    def init(self):
        self.wes = self.main.wesSock
        self.irc = self.main.irc

    def onIrcMessage(self, data):
        self.log.debug("with unparsed irc message in commandhandler %s", data)
        # message = data.split('#',1)[1].split(":",1)[1].strip("\r\n")
        message = data.split(":", 2)[2]
        sender = data[1:].split("!", 1)[0]
        if sender == "IRC":
            if "Too many connections from your IP" in message:
                net_ = self.main.cfg.ircNetAlt
                if self.main.cfg.ircNet in net_:
                    net_.remove(self.main.cfg.ircNet)
                    self.main.cfg.ircNet = random.choice(list(net_))
                    raise WesException().reconnectIrc()
            return  # Message from IRC network, not something that should be treated as user message
        target = data.split(" ", 3)[2]
        self.log.debug("target %s", target)
        whisper = "#" not in target
        self.log.debug("with irc message in commandhandler %s %s %s", sender, ">", message)
        permission = 0
        if sender in self.ircMasters:
            permission = PERMISSION_ADMIN + 5

        self.onMessage(message, sender, permission, "irc", whisper)

    def onWesMessage(self, message, sender, registered=False, whisper=False):
        cfg = self.main.cfg
        # possibly server does not use registrations
        self.log.log(6, "with wes message in commandhandler, sender=%s, message=%s, registered=%s, whisper=%s", sender,
                     message, registered, whisper)
        permission = 0
        if cfg.serverName == "localhost" and sender in self.wesMasters:
            permission = PERMISSION_ADMIN + 1
        if registered and sender in self.wesMasters:
            permission = PERMISSION_ADMIN + 9
        elif registered and sender in self.main.cfg.botTrustedNames:
            permission = PERMISSION_TRUSTED + 9
        elif registered:
            permission = PERMISSION_REGISTERED + 1

        self.onMessage(message, sender, permission, "wes", whisper)

    def onMessage(self, message: str, sender, permission, origin, private=False):
        cfg = self.main.cfg
        if private:
            self.logOnIrc("<{}> -> <{}>: {}".format(sender, cfg.username, message))
        elif origin == "wes":
            self.main.messageLog.info("<%s> %s", sender, message)

        self.log.info("Received generic message with info: sender=%s, message=%s, permission=%s, type=%s, private=%s",
                      sender, message, permission, origin, private)
        if sender == "server" and origin == "wes":
            self.onServerMessage(message, private)
            return
        if permission < PERMISSION_TRUSTED and not private:
            if cfg.username in message:
                self.onCommand("help", sender, permission, origin)
            return
        if message.startswith(self.prefix):
            self.onCommand(message[len(self.prefix):], sender, permission, origin)
        elif message == "help" and private:
            self.onCommand("help", sender, permission, origin)
        elif cfg.username in message and private:
            self.onCommand("help", sender, permission, origin)
        elif private and permission < PERMISSION_TRUSTED:
            self.sendPrivately(
                sender, origin, "Message not recognized. You are {} with permission {}. Try using {}help and {}commands".format(
                    sender, permission, self.prefix, self.prefix))

    def onCommand(self, message, sender, permission, origin):
        def reply(message):
            self.sendPrivately(sender, origin, str(message))

        if " " in message:
            message = message.split(" ", 1)
            command = message[0]
            args = message[1]
        else:
            command = message
            args = ""
        self.log.debug("got command %s %s %s", command, "with args", args)

        if command in self.commands and permission > self.commands[command].permission:
            self.commands[command].command(reply=reply, args=args, permission=permission, sender=sender)

        if command == "join" and permission > PERMISSION_ADMIN:
            self.irc.join(args)
        elif command == "part" and permission > PERMISSION_ADMIN:
            self.irc.part(args)
        elif command == "quitwes" and permission > PERMISSION_ADMIN:
            raise WesException("quitwes command used").addAction(WesException.QUIT_WES)
        elif command == "quitirc" and permission > PERMISSION_ADMIN:
            raise WesException("quitirc command used").addAction(WesException.QUIT_IRC)
        elif command == "ircreconnect" and permission > PERMISSION_ADMIN:
            raise WesException("ircreconnect command used").reconnectIrc()
        elif command == "wesreconnect" and permission > PERMISSION_ADMIN:
            raise WesException("wesreconnect command used").reconnectWes()
        elif command == "follow" and permission > PERMISSION_ADMIN:
            if not args or args == "":
                args = sender
            try:
                user = self.main.lobby.users.get(args)
                self.wes.send_wml_string("[join]\nid={}\nobserve=yes\n[/join]".format(user.game_id))
            except WesException as e:
                if e.action != [WesException.ASSERT]:
                    raise e
                reply("User {} not found".format(args))
        elif command == "control" and permission > PERMISSION_ADMIN:
            parts = args.split(" ", 1)
            if len(parts) == 2:
                side, target = parts[0], parts[1]
                self.wes.send_wml_string("""[change_controller]
controller="human"
player="%s"
side="%s"
[/change_controller]""" % (target, side))
            else:
                reply("control needs to have two arguments")
        elif command == "leave" and permission > PERMISSION_ADMIN:
            self.wes.send_wml_string("[leave_game]\n[/leave_game]")
        elif command == "trust" and permission > PERMISSION_ADMIN:
            self.main.cfg.botTrustedNames.append(args.strip())
            reply("Added '{}' to trusted names. Current list: {}".format(args.strip(), self.main.cfg.botTrustedNames))
        else:
            if command not in self.commands:
                reply("Command {} not recognized".format(command))

    def initializeCommands(self):
        # {reply: reply, args: args, permission: permission, sender: sender}
        def raw(**kwargs):
            try:
                with open("raw.cfg", "r", encoding="utf8") as f:
                    self.wes.send_wml_string("".join(f.readlines()))
            except Exception as e:
                self.main.log.warning("raw failed", e)

        def uptime(**kwargs):
            """Tells how long bot has been running, and how long it has been online since wesnothd last sent illegal user info
No arguments"""
            # TODO round times
            kwargs["reply"]("Time since first connect: {}, time since last connect: {}"
                            .format(self.main.lobby.stats.getTimeSinceFirstConnect(),
                                    self.main.lobby.stats.getTimeSinceLastConnect()))

        def userstats(**kwargs):
            """Finds when and for how long user $1 has been online
$1 = name of user to query"""
            # TODO round times
            kwargs["reply"](self.main.lobby.stats.getUserStats(kwargs["args"]))

        def save(**kwargs):
            """Debug command to trigger writing user events to file"""
            self.main.lobby.stats.saveUsers()
            kwargs["reply"]("Users saved")

        def gcUsers(**kwargs):
            """Debug command to delete user events of users not seen in last 10 min"""
            self.main.lobby.stats.deleteOldData(datetime.datetime.now(), datetime.timedelta(minutes=10))
            kwargs["reply"]("Users garbage collection done")

        def gitPull(**kwargs):
            """Command to run git pull"""
            process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE)
            output = process.communicate()[0]
            if isinstance(output, bytes):
                output = output.decode("utf8")
            kwargs["reply"]("git pull: {}".format(output))

        def stats(**kwargs):
            """Command to get basic lobby statistics. Might not work correctly currently"""
            kwargs["reply"]("Game stats: {}, User stats: {}".format(self.main.lobby.games.getStats(),
                                                                    self.main.lobby.users.getStats()))

        def say(**kwargs):
            """Say $1 publicly, usually in lobby. Doesnt seem to work from in game in 1.14
$1 = message"""
            # default is say on lobby, even when user is currently in game
            # TODO not default anymore, seems message is just ignored
            if len(kwargs["args"]) == 0:
                kwargs["reply"]("message is required")
            else:
                self.sayOnWesnoth(kwargs["args"])

        def m(**kwargs):
            """Send private message $2- to user $1. Trusted users can only message Trusted+ users.
$1 = receiver user name
$2- = message"""
            if " " not in kwargs["args"]:
                kwargs["reply"]("Too few arguments")
                return
            receiver, msg = kwargs["args"].split(" ", 1)
            receiver = receiver.strip()
            if kwargs["permission"] > PERMISSION_ADMIN \
                    or receiver in self.main.cfg.botTrustedNames \
                    or receiver in self.wesMasters:
                self.sendPrivately(receiver, "wes", msg)
            else:
                kwargs["reply"]("Currently trusted users can only message to another trusted users and admins")

        def alias(**kwargs):
            """Creates alias $1 which points to command $2"""
            if " " not in kwargs["args"]:
                kwargs["reply"]("Not enough arguments")
                return
            parts = kwargs["args"].split(" ", 1)
            if len(parts[0]) > 0 and len(parts[1]) > 0 and parts[0] not in self.commands and parts[1] in self.commands:
                self.commands[parts[0]] = self.commands[parts[1]]
                kwargs["reply"]("Alias added")
            else:
                kwargs["reply"]("Alias not added")

        def q(**kwargs):
            """Quits bot"""
            kwargs["reply"]("quitting")
            raise WesException("quit command used").quit()

        def restart(**kwargs):
            """Restarts bot"""
            kwargs["reply"]("restarting")
            raise WesException("restart command used").restart()

        def commandsHelp(**kwargs):
            """List of available commands, or help message of command $1
[$1 = command name]"""
            if kwargs["args"] in self.commands:
                kwargs["reply"]("Command {} for permission {}+ (yours: {}): {}".format(kwargs["args"], self.commands[
                    kwargs["args"]].permission, kwargs["permission"], self.commands[kwargs["args"]].command.__doc__))
            else:
                publicCommands = []
                trustedCommands = []
                adminCommands = []
                otherCommands = []
                for name, command in self.commands.items():
                    if command.permission == PERMISSION_PUBLIC:
                        publicCommands.append(name)
                    elif command.permission == PERMISSION_TRUSTED:
                        trustedCommands.append(name)
                    elif command.permission == PERMISSION_ADMIN:
                        adminCommands.append(name)
                    else:
                        otherCommands.append(name)
                kwargs["reply"]("Available commands for PUBLIC: {}, TRUSTED: {}, ADMIN: {}. "
                                "Use <{}commands command> for command description"
                                .format(sorted(publicCommands), sorted(trustedCommands), sorted(adminCommands),
                                        self.prefix))

        def addPing(**kwargs):
            """Sender will be sent "ping" private message every $1 minutes
$1 = number, default 1. Use <=1 to remove ping, example 0"""
            interval = 1
            try:
                interval = int(kwargs["args"])
            except:
                kwargs["reply"]("Invalid time format, using default")
            if interval < 1:
                del self.pingUsers[kwargs["sender"]]
                kwargs["reply"]("You will not be pinged anymore")
            else:
                self.pingUsers[kwargs["sender"]] = (interval, datetime.datetime.now())
                kwargs["reply"]("You will be pinged every {} minutes".format(interval))

        self.commands = {
            "raw": Command(PERMISSION_ADMIN, raw),
            "uptime": Command(PERMISSION_PUBLIC, uptime),
            "users": Command(PERMISSION_PUBLIC, lambda **kwargs: kwargs["reply"](self.main.lobby.users.getUsers())),
            "games": Command(PERMISSION_PUBLIC, lambda **kwargs: kwargs["reply"](self.main.lobby.games.getGames())),
            "online": Command(PERMISSION_PUBLIC,
                              lambda **kwargs: kwargs["reply"](self.main.lobby.users.getOnlineUsers())),
            "stats": Command(PERMISSION_PUBLIC, stats),
            "help": Command(PERMISSION_PUBLIC, lambda **kwargs: kwargs["reply"](self.HELP_MESSAGE)),
            "ping": Command(PERMISSION_PUBLIC, addPing),
            "user": Command(PERMISSION_TRUSTED, userstats),
            "save": Command(PERMISSION_ADMIN, save),
            "gc": Command(PERMISSION_ADMIN, gcUsers),
            "pull": Command(PERMISSION_ADMIN, gitPull),
            "say": Command(PERMISSION_ADMIN, say),
            "m": Command(PERMISSION_TRUSTED, m),
            "alias": Command(PERMISSION_ADMIN, alias),
            "q": Command(PERMISSION_ADMIN, q),
            "restart": Command(PERMISSION_ADMIN, restart),
            "commands": Command(PERMISSION_PUBLIC, commandsHelp)
        }

    def sayOnWesnoth(self, message, room=""):
        if type(message) != type(""):
            message = repr(message)
        self.logOnIrc("->{}: {}".format(room, message))
        self.wes.send_wml_string(
            '[message]\nmessage="' + re.sub('"', '""', message) + '"\nroom="' + room + '"\n[/message]\n')

    def whisperOnWesnoth(self, target, message):
        cfg = self.main.cfg
        self.logOnIrc("<{}> -> <{}>: {}".format(cfg.username, target, message))
        self.wes.send_wml_string('[whisper]\nmessage="' + re.sub('"', '""', message) +
                                 '"\nreceiver="' + target + '"\nsender="spoof"\n[/whisper]\n')

    def sendPrivately(self, sender, origin, message):
        if type(message) != type(""):
            message = repr(message)
        if origin == "irc":
            self.irc.whisper(sender, message)
        elif origin == "wes":
            self.whisperOnWesnoth(sender, message)

    def logOnIrc(self, message):
        cfg = self.main.cfg
        self.main.messageLog.info(message)
        if cfg.ircEnabled:
            if self.irc:
                self.irc.say(message)
            else:
                self.log.error("logOnIrc called when irc does not exist")

    def onServerMessage(self, message: str, private):
        self.log.info("Got server message: " + message)
        if "The server has been restarted" in message and not private:
            raise WesException().reconnectWes()
        if "Can't find '" in message:
            name = message.split("'")[2]
            self.log.info("User " + name + "is offline")
            del self.pingUsers[name]

    def tick(self):
        now: datetime = datetime.datetime.now()
        for user in self.pingUsers:
            # if user not in online:
            #    continue
            interval, lastPing = self.pingUsers[user]
            if lastPing + datetime.timedelta(minutes=interval) < now:
                self.whisperOnWesnoth(user, "ping")
                self.pingUsers[user] = (interval, now)
