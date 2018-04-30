import logging
import logging.handlers
import gzip
import socket
import subprocess
import os

import wmlparser
import typing

if typing.TYPE_CHECKING:
    from rewritebot import WesBot
from rewritebotSCHEMA import WesException


class WesSock:
    socketTimeout = 1
    sock: socket.socket

    def __init__(self, main: 'WesBot', version: str):
        self.main = main
        self.wesnothVersion = version
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(WesSock.socketTimeout)
        self.log_sent = logging.getLogger("CON sent")
        self.log_rec = logging.getLogger("CON rec")
        fh_send = logging.handlers.RotatingFileHandler("log/wesbot_sent.log", maxBytes=10 * 1024 * 1024, backupCount=2)
        fh_rec = logging.handlers.RotatingFileHandler("log/wesbot_rec.log", maxBytes=10 * 1024 * 1024, backupCount=2)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh_send.setFormatter(formatter)
        fh_rec.setFormatter(formatter)
        self.log_sent.setLevel(logging.DEBUG)
        self.log_rec.setLevel(logging.DEBUG)
        if (self.log_sent.hasHandlers()):
            self.log_sent.handlers.clear()
        if (self.log_rec.hasHandlers()):
            self.log_rec.handlers.clear()
        self.log_sent.addHandler(fh_send)
        self.log_rec.addHandler(fh_rec)

    def connect(self, host, port=15000):
        self.sock.connect((host, port))
        # and ensure correct port
        self._handshake()
        if "[version]" not in self.receive_string():
            raise WesException("Server did not ask for version").quit()

        self.send_wml_string('[version]\nversion="' + self.wesnothVersion + '"\n[/version]\n')

        response = self.receive_string()
        parser = wmlparser.Parser(None)
        wml = parser.parse_text(response)
        result = {}
        if type(wml) is wmlparser.RootNode:
            wml = wml.get_all()
            for i in wml:
                for j in i.get_all():
                    result[j.get_name()] = j.get_text()
        if "port" in result:
            self.main.log.debug("need to use different port %s", result)
            self.shutdown()
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(WesSock.socketTimeout)
            self.connect(result["host"], int(result["port"]))

    def loginLobby(self, name, password) -> bool:
        self.send_wml_string('[login]\npassword=""\nusername="' + name + '"\n[/login]')
        result = self.receive_string()
        self.main.log.info("Login process: %s", result)

        if "[join_lobby]\n[/join_lobby]" == result.strip():
            return True
        resultList = result.splitlines()

        salt = ""
        for line in resultList:
            if line.split("=")[0] == "salt":
                salt = line.split("=")[1]

        if salt != "":
            if os.name == "nt":
                process = subprocess.Popen('hashwes.exe' + ' ' + password + ' ' + salt,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
            else:
                # segmentation fault without that strip
                salt = salt.strip('"')
                process = subprocess.Popen("./hashwes '{}' '{}'".format(password, salt),
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
            passhash = process.communicate()[0].decode("utf8")
            self.main.log.info("receive passhash %s from salt %s on user %s", passhash, salt, name)
            self.send_wml_string(
                '[login]\nforce_confirmation="yes"\npassword="' + passhash + '"\nusername="' + name + '"\n[/login]')
            result = self.receive_string()
        self.main.log.debug("Auth process: %s", result)
        if "[join_lobby]\n[/join_lobby]" == result.strip():
            return True
        if 'incorrect."\npassword_request="yes"' in result:
            self.main.log.warn("Login failed, wrong password hash")
        elif 'password_request="yes"' in result:
            self.main.log.warn("Login failed, no password hash")
        elif 'is already taken.' in result:
            self.main.log.warn("Login failed, name taken, no registering")
            return self.loginLobby(name + "_", "")
        return False

    def _send_bytes(self, msg: bytes):
        totalsent = 0
        MSGLEN = len(msg)
        while totalsent < MSGLEN:
            sent = self.sock.send(msg[totalsent:])
            if sent == 0:
                raise WesException("socket connection broken").addAction(WesException.QUIT_WES)
            totalsent = totalsent + sent

    def send_wml_string(self, msg):
        if type(msg) != type(""):
            msg = repr(msg)
        self.log_sent.debug(msg)
        msg = msg.encode()
        msg = gzip.compress(msg)
        msg = bytes(msg)
        msglen = (len(msg)).to_bytes(4, byteorder='big')
        self._send_bytes(msglen + msg)

    def _handshake(self):
        self._send_bytes(bytes([0x00, 0x00, 0x00, 0x00]))
        reply = self.sock.recv(4)
        self.main.log.debug("handshake reply %s %s %s", reply, "socket number", int.from_bytes(reply, byteorder="big"))

    def _receive_byte_string(self) -> bytes:
        try:
            chunks = []
            bytes_recd = 0
            chunk = self.sock.recv(4)

            bytes_wanted = int.from_bytes(chunk, byteorder="big")
            while bytes_recd != bytes_wanted:
                chunk = self.sock.recv(min(1024, bytes_wanted - bytes_recd))
                if not chunk:
                    self.main.log.warn("chunk not")
                    break
                if chunk == b'':
                    raise WesException("socket connection broken").addAction(WesException.QUIT_WES)
                chunks.append(chunk)

                bytes_recd = bytes_recd + len(chunk)

            result: bytes = gzip.decompress(b''.join(chunks))
            if len(result) == 0:
                raise WesException("Received empty, so quitting").addAction(WesException.QUIT_WES)
            self.log_rec.debug(result)
            return result
        except socket.timeout:
            return b''

    def receive_string(self) -> str:
        return self._receive_byte_string().decode("utf8")

    def shutdown(self):
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
