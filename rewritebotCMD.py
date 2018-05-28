import datetime
import logging
import logging.handlers
import random
import re
import subprocess

from rewritebotSCHEMA import WesException
import typing

if typing.TYPE_CHECKING:
    from rewritebot import WesBot

PERMISSION_ADMIN = 90
PERMISSION_TRUSTED = 50
PERMISSION_REGISTERED = 10
PERMISSION_PUBLIC = -1


class Command:
    def __init__(self, permission: int, command: 'function'):
        self.command = command
        self.permission = permission


class CommandHandler:
    def __init__(self, main: 'WesBot', wesMasters, ircMasters):
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
        self.log.debug("with wes message in commandhandler, sender=%s, message=%s, registered=%s, whisper=%s", sender,
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
            self.main.messageLog.info("<%s> %s | private=%s", sender, message, private)

        self.log.info("Received generic message with info: sender=%s, message=%s, permission=%s, type=%s, private=%s",
                      sender, message, permission, origin, private)
        if sender == "server" and origin == "wes":
            self.onServerMessage(message, private)
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
        elif private:
            self.sendPrivately(sender, origin,
                               "Message not recognized. You are {} with permission {}".format(sender, permission))

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

        def uptime():
            # TODO round times
            reply("Time since first connect: {}, time since last connect: {}"
                  .format(self.main.lobby.stats.getTimeSinceFirstConnect(),
                          self.main.lobby.stats.getTimeSinceLastConnect()))

        def userstats():
            # TODO round times
            reply(self.main.lobby.stats.getUserStats(args))

        def save():
            self.main.lobby.stats.saveUsers()
            reply("Users saved")

        def gcUsers():
            self.main.lobby.stats.deleteOldData(datetime.datetime.now(), datetime.timedelta(minutes=10))
            reply("Users garbage collection done")

        def gitPull():
            process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE)
            output = process.communicate()[0]
            if isinstance(output, bytes):
                output = output.decode("utf8")
            reply("git pull: {}".format(output))

        # TODO not recognized is also displayed
        commands = {
            "uptime": (PERMISSION_PUBLIC, uptime),
            "user": (PERMISSION_TRUSTED, userstats),
            "save": (PERMISSION_ADMIN, save),
            "gc": (PERMISSION_ADMIN, gcUsers),
            "pull": (PERMISSION_ADMIN, gitPull)
        }

        if command in commands and permission > commands[command][0]:
            commands[command][1]()

        if command == "join" and permission > PERMISSION_TRUSTED:
            self.irc.join(args)
        elif command == "part" and permission > PERMISSION_TRUSTED:
            self.irc.part(args)
        elif command == "help":
            self.sendPrivately(sender, origin, self.HELP_MESSAGE)
        elif command == "quit" and permission > PERMISSION_ADMIN:
            raise WesException("quit command used").quit()
        elif command == "quitwes" and permission > PERMISSION_ADMIN:
            raise WesException("quitwes command used").addAction(WesException.QUIT_WES)
        elif command == "quitirc" and permission > PERMISSION_ADMIN:
            raise WesException("quitirc command used").addAction(WesException.QUIT_IRC)
        elif command == "restart" and permission > PERMISSION_ADMIN:
            raise WesException("restart command used").restart()
        elif command == "ircreconnect" and permission > PERMISSION_ADMIN:
            raise WesException("ircreconnect command used").reconnectIrc()
        elif command == "wesreconnect" and permission > PERMISSION_ADMIN:
            raise WesException("wesreconnect command used").reconnectWes()
        elif command == "users" and permission > PERMISSION_TRUSTED:
            reply(self.main.lobby.users.getUsers())
        elif command == "games" and permission > PERMISSION_TRUSTED:
            reply(self.main.lobby.games.getGames())
        elif command == "online" and permission > PERMISSION_TRUSTED:
            reply(self.main.lobby.users.getOnlineUsers())
        elif command == "follow" and permission > PERMISSION_TRUSTED:
            if not args or args == "":
                args = sender
            try:
                user = self.main.lobby.users.get(args)
                self.wes.send_wml_string("[join]\nid={}\nobserve=yes\n[/join]".format(user.game_id))
            except WesException as e:
                if e.action != [WesException.ASSERT]:
                    raise e
                reply("User {} not found".format(args))

        elif command == "say" and permission > PERMISSION_TRUSTED:
            # default is say on lobby, even when user is currently in game
            # TODO not default anymore, seems message is just ignored
            self.sayOnWesnoth(args)
        elif command == "m" and permission > PERMISSION_TRUSTED:
            receiver, msg = args.split(" ", 1)
            self.sendPrivately(receiver, "wes", msg)
        elif command == "control" and permission > PERMISSION_TRUSTED:
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
        elif command == "leave" and permission > PERMISSION_TRUSTED:
            self.wes.send_wml_string("[leave_game]\n[/leave_game]")
        elif command == "trust" and permission > PERMISSION_ADMIN:
            self.main.cfg.botTrustedNames.append(args.strip())
            reply("Added '{}' to trusted names. Current list: {}".format(args.strip(), self.main.cfg.botTrustedNames))
        elif command == "stats":
            reply("Game stats: {}, User stats: {}".format(self.main.lobby.games.getStats(),
                                                          self.main.lobby.users.getStats()))
        else:
            if command not in commands:
                reply("Command {} not recognized".format(command))

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

    def onServerMessage(self, message, private):
        if "The server has been restarted" in message and not private:
            raise WesException().reconnectWes()
