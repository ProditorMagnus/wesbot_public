import logging
import logging.handlers
import socket
import typing

from rewritebotSCHEMA import WesException

if typing.TYPE_CHECKING:
    from rewritebot import WesBot


class WesIrc:
    socketTimeout = 1
    port = 6667

    def __init__(self, main: 'WesBot'):
        self.main = main
        cfg = self.main.cfg

        self.connected = False
        self.auth = False
        self.inChannel = False

        self.network = cfg.ircNet
        self.homechan = cfg.ircChan
        self.log = logging.getLogger("IRC")
        fh = logging.handlers.RotatingFileHandler("log/wesbot_irc.log", encoding="utf8", maxBytes=10 * 1024 * 1024,
                                                  backupCount=2)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        self.log.setLevel(logging.DEBUG)
        if (self.log.hasHandlers()):
            self.log.handlers.clear()
        self.log.addHandler(fh)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(WesIrc.socketTimeout)
        self.responseBuffer = ""

    def connect(self):
        self.sock.connect((self.network, self.port))
        self.connected = True
        if not self.auth:
            self.login()
        # self.receive()

    def login(self):
        cfg = self.main.cfg
        self.send('PASS {}\r\n'.format(cfg.ircPass))
        self.send('NICK {}\r\n'.format(cfg.ircName))
        self.send('USER {} {} {} :Python IRC\r\n'.format(cfg.ircName, cfg.ircName, cfg.ircName))

    def ensure_connected(self):
        cfg = self.main.cfg
        if not self.connected:
            self.connect()
        if not self.auth:
            self.login()
        if not self.inChannel:
            self.join(cfg.ircChan)

    def send(self, msg: str):
        if not self.connected:
            self.log.warning("send called without connection")
            return
        # print("sending",msg)
        if msg.startswith("PONG"):
            self.log.log(5, "send %s", msg.strip())
        else:
            self.log.debug("send %s", msg.strip())
        self.sock.send(msg.encode())

    def say(self, msg: str):
        if type(msg) != type(''):
            msg = repr(msg)
        msg = msg.replace("\n", " ")
        msg = msg.replace("\r", "")
        if not self.connected:
            self.log.warning("say called without connection")
            return
        self.log.debug("send %s", ('PRIVMSG ' + self.homechan + ' :' + msg + '\r\n').strip())
        msg = msg.replace("Laela", "L" + u"\u200B" + "aela")
        msg = msg.replace("Ravana", "R" + u"\u200B" + "avana")
        # print("saying",msg)
        self.sock.send(('PRIVMSG ' + self.homechan + ' :' + msg + '\r\n').encode())

    def whisper(self, target: str, msg: str):
        if type(msg) != type(''):
            msg = repr(msg)
        msg = msg.replace("\n", " ")
        msg = msg.replace("\r", "")
        if not self.connected:
            self.log.warning("whisper called without connection")
            return
        msg = msg.replace("Laela", "L" + u"\u200B" + "aela")
        msg = msg.replace("Ravana", "R" + u"\u200B" + "avana")
        self.log.debug("send %s", ('PRIVMSG ' + target + ' :' + msg + '\r\n').strip())
        self.sock.send(('PRIVMSG ' + target + ' :' + msg + '\r\n').encode())

    def receive(self):
        try:
            response: str = self.sock.recv(4096).decode("utf8")
            response = self.responseBuffer + response
            self.responseBuffer = ""
            splitlines = response.splitlines(True)
            unhandledResponse = ""
            for i in range(len(splitlines)):
                line = splitlines[i]
                if len(line) == len(line.rstrip()):
                    if i == len(splitlines) - 1:
                        # Save it to buffer
                        self.responseBuffer = line
                        break
                    else:
                        # Line does not end with newline symbol, but there is another line somehow, should never happen
                        raise WesException("line without newline but is not last").addAction(WesException.QUIT_IRC)
                if not self._actOnLine(line):
                    unhandledResponse += line
            return unhandledResponse
        except socket.timeout:
            self.ensure_connected()
            return ""

    def _actOnLine(self, line):
        if line.startswith("PING"):
            self.log.log(5, "recv %s", line.strip())
            self.send(line.replace("PING", "PONG", 1).strip("\r\n") + "\r\n")
            return True
        self.log.debug("recv %s", line.strip())
        # TODO filter it to avoid spoofing this message
        if "451 JOIN :You have not registered" in line:
            self.login()
            return True
        if ":NickServ MODE {} :+r".format(self.main.cfg.ircName) == line.strip():
            self.auth = True
            self.join(self.homechan)
            return True
        # TODO filter it to avoid spoofing this message
        if "MODE {} +o {}".format(self.homechan, self.main.cfg.ircName) in line:
            self.inChannel = True
            return True
        return False

    def join(self, chan: str):
        self.send(('JOIN ' + chan + '\r\n'))

    def part(self, chan: str):
        self.send(('PART ' + chan + '\r\n'))

    def shutdown(self):
        if self.connected:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self.connected = False
