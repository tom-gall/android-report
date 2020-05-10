#!/usr/bin/env python3

# https://www.techbeamers.com/create-python-irc-bot/
import socket
import sys
import threading
import time

from lcr.settings import IRC_CONFIG

class IRC:

    __instance = None
    irc_socket = None
    server = None
    port = None
    channel = None
    botnick = None
    botpass = None
    botnickpass = None

    func_listener = {}

    @staticmethod
    def getInstance():
        """ Static access method. """
        if IRC.__instance == None:
            IRC()
        return IRC.__instance

    def __init__(self):
        """ Virtually private constructor. """

        if IRC_CONFIG is None \
            or IRC_CONFIG.get('enable') is None \
            or not IRC_CONFIG.get('enable'):
            return None

        if IRC.__instance != None:
            raise Exception("This class is a singleton!")
        else:
            self.irc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            configs = IRC_CONFIG.get('configs')
            if configs:
                self.server = configs.get('server')
                self.port = configs.get('port')
                self.channel = configs.get('channel')
                self.botnick = configs.get('botnick')
                self.botpass = configs.get('botpass')
                self.botnickpass = configs.get('botnickpass')
                self.connect()

                t = threading.Thread(target=self.dealWithFunctions, args=())
                t.start()

        IRC.__instance = self


    def dealWithFunctions(self):
        while True:
            text = self.get_response()
            for key_word, irc_func in self.getFuncions().items():
                #if resp.find('PING') != -1:
                if text and key_word in text:
                    irc_func(self, text)
            time.sleep(1)


    def addFunctions(self, func_dict={}):
        self.func_listener.update(func_dict)


    def getFuncions(self):
        return self.func_listener


    def send(self, msgStrOrAry=None):
        if self.irc_socket is None or msgStrOrAry is None:
            return None

        # Transfer data
        if type(msgStrOrAry) == list:
            for msg in msgAry:
                msg_out = "PRIVMSG %s : %s\r\n" % (self.channel, str(msg))
                self.irc_socket.send(bytes(msg_out, "UTF-8"))
        else:
            msg_out = "PRIVMSG %s : %s\r\n" % (self.channel, str(msgStrOrAry))
            self.irc_socket.send(bytes(msg_out, "UTF-8"))


    def connectWithConfigs(self, server, port, channel, botnick, botpass, botnickpass):
        if self.irc_socket is None:
            return None

        # Connect to the server
        print("Connecting to: " + self.server)
        self.irc_socket.connect((self.server, int(self.port)))

        # Perform user authentication
        self.irc_socket.send(bytes("USER " + self.botnick + " " + self.botnick +" " + self.botnick + " :python\n", "UTF-8"))
        print("after send command USER to: " + self.server)
        self.irc_socket.send(bytes("NICK " + self.botnick + "\n", "UTF-8"))
        print("after send command NICK to: " + self.server)
        #self.irc.send(bytes("NICKSERV IDENTIFY " + self.botnickpass + " " + self.botpass + "\n", "UTF-8"))
        time.sleep(5)

        # join the channel
        self.irc_socket.send(bytes("JOIN " + self.channel + "\n", "UTF-8"))
        time.sleep(10)
        print("joined to: " + self.channel)


    def connect(self):
        if self.irc_socket is None:
            return None
        self.connectWithConfigs(self.server, self.port, self.channel, self.botnick, self.botpass, self.botnickpass)


    # only deal with the message to this irc nick and channel
    def get_response(self):
        if self.irc_socket is None:
            return None

        time.sleep(1)
        # Get the response
        resp = self.irc_socket.recv(2040).decode("UTF-8")

        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        if not "PRIVMSG" in resp \
                or not self.channel in resp \
                or not self.botnick in resp:
            return None

        return resp


def func_hello(irc=None, text=""):
    import datetime
    if irc is not None and text:
        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        irc.send('Hello %s, the time is %s now:' % (text.split('!')[0].strip(':'), str(datetime.datetime.now())))


def func_ping(irc=None, text=""):
    if irc is not None and text:
        user = text.split('!')[0].strip(':')
        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        irc.send('PONG ' + user)


def main():
    irc = IRC().getInstance()

    func_listener = {
        'hello': func_hello,
        'ping': func_ping,
    }

    irc.addFunctions(func_listener)

if __name__ == "__main__":
    main()
