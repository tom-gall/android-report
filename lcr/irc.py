#!/usr/bin/env python3

# https://www.techbeamers.com/create-python-irc-bot/
# https://linuxacademy.com/blog/linux-academy/creating-an-irc-bot-with-python3/
# https://tools.ietf.org/html/rfc1459
# https://freenode.net/kb/answer/registration
import datetime
import logging
import socket
import sys
import threading
import time


from lcr.settings import IRC_CONFIG

logger = logging.getLogger(__name__)

class IRC:

    __instance = None
    irc_socket = None
    server = None
    port = None
    channel = None
    botnick = None
    botpass = None

    func_listener = {}

    @staticmethod
    def getInstance():
        """ Static access method. """
        #if IRC.__instance == None:
        return IRC()
        #return IRC.__instance

    def __init__(self):
        """ Virtually private constructor. """

        if IRC_CONFIG is None \
            or IRC_CONFIG.get('enable') is None \
            or not IRC_CONFIG.get('enable'):
            return None

        configs = IRC_CONFIG.get('configs')
        if configs:
            self.server = configs.get('server')
            self.port = configs.get('port')
            self.channel = configs.get('channel')
            self.botnick = configs.get('botnick')
            self.botpass = configs.get('botpass')

        #if IRC.__instance != None:
        #    raise Exception("This class is a singleton!")
        #else:
        #    IRC.__instance = self
#            self.connect()
#            self.addFunctions(func_dict={
#                    'PING': self.func_pong,
#                    })

#            t = threading.Thread(target=self.dealWithFunctions, args=())
#            t.start()


    def func_pong(self, irc=None, text=""):
        # to workaround the ping from server
        if irc.irc_socket:
            irc.irc_socket.send(bytes("PONG", "UTF-8"))

    def dealWithFunctions(self):
        while True:
            text = self.get_response()
            for key_word, irc_func in self.getFuncions().items():
                #if resp.find('PING') != -1:
                if text and (text.find(key_word) != -1):
                    irc_func(self, text)
            time.sleep(1)

    # TODO need to be thread safe
    def addFunctions(self, func_dict={}):
        for key in func_dict.keys():
            logger.info("regiester irc founction: %s" % key)
        self.func_listener.update(func_dict)


    def getFuncions(self):
        return self.func_listener


    def send(self, msgStrOrAry=None):
        if self.irc_socket is None or msgStrOrAry is None:
            return None

        # Transfer data
        if type(msgStrOrAry) == list:
            for msg in msgStrOrAry:
                msg_out = "PRIVMSG %s : %s\r\n" % (self.channel, str(msg))
                len_sent = self.irc_socket.send(bytes(msg_out, "UTF-8"))
                #len_expect = len(bytes(msg_out, "UTF-8"))
                time.sleep(1) # to workaround the excess flood problem
                #if len_expect != len_sent:
                #logger.info("not all bytes sent for msg: %s, sent %d, expected:%d" % (msg_out, len_sent, len_expect))
        else:
            msg_out = "PRIVMSG %s : %s\r\n" % (self.channel, str(msgStrOrAry))
            len_sent = self.irc_socket.send(bytes(msg_out, "UTF-8")) # [Errno 32] Broken pipe
            #len_expect = len(bytes(msg_out, "UTF-8"))
            #if len_expect != len_sent:
            #    logger.info("not all bytes sent for msg: %s, sent %d, expected:%d" % (msg_out, len_sent, len_expect))


    def quit(self):
        if self.irc_socket:
            self.irc_socket.send(bytes("QUIT", "UTF-8"))
            logger.info("sent quit")
            #time.sleep(1) # (Write error: Connection reset by peer)
            self.irc_socket.close() # [Errno 106] (EISCONN) Transport endpoint is already connected
            self.irc_socket = None  # [Errno 9] Bad file descriptor reported when the socket was closed
            self.__instance = None  # [Errno 9] Bad file descriptor


    def sendAndQuit(self, msgStrOrAry=None):
        if self.server is None:
            # should be only available when irc notification enabled
            return
        else:
            self.connect()
            self.send(msgStrOrAry=msgStrOrAry)
            time.sleep(3) # workaround for Ping timeout: 260 seconds
            self.quit()


    def connectWithConfigs(self, server, port, channel, botnick, botpass):
        if self.irc_socket is None:
            self.irc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Connect to the server
        logger.info("Connecting to: " + self.server)
        self.irc_socket.connect((self.server, int(self.port)))

        # Perform user authentication
        self.irc_socket.send(bytes("USER " + self.botnick + " " + self.botnick +" " + self.botnick + " :python\n", "UTF-8"))
        logger.info("after send command USER to: " + self.server)
        self.irc_socket.send(bytes("NICK " + self.botnick + "\n", "UTF-8"))
        logger.info("after send command NICK to: " + self.server)
        self.irc_socket.send(bytes("NICKSERV IDENTIFY " + self.botpass + "\n", "UTF-8"))

        str_idenfified = "You are now identified for"
        identified = False
        sleep_time = 0
        while not identified:
            if sleep_time > 25:
                logger.info("Failed to identify for the account of %s after %d seconds" % (self.botnick, sleep_time))
                break
            text = self.irc_socket.recv(2040).decode("UTF-8")
            if text.find(str_idenfified) != -1:
                logger.info("found identified message")
                identified = True
            else:
                logger.debug("%d: not found identified message" % sleep_time)
                time.sleep(3)
                sleep_time = sleep_time + 3

        # continue to try, but the result won't be as expected
        # join the channel
        logger.info("Try to join: " + self.channel)
        self.irc_socket.send(bytes("JOIN " + self.channel + "\n", "UTF-8"))
        str_joined = ":End of /NAMES list"
        joined = False
        sleep_time = 0
        while not joined:
            if sleep_time > 25:
                logger.info("Failed to join %s " % self.channel)
                break
            text = self.irc_socket.recv(2040).decode("UTF-8")
            if text.find(str_joined) != -1:
                logger.info("found joined message")
                joined = True
            else:
                logger.debug("%d not found joined message" % sleep_time)
                time.sleep(3)
                sleep_time = sleep_time + 3
        logger.info("joined to: " + self.channel)


    def connect(self):
        self.connectWithConfigs(self.server, self.port, self.channel, self.botnick, self.botpass)


    # only deal with the message to this irc nick and channel
    def get_response(self):
        if self.irc_socket is None:
            return None

        time.sleep(1)
        # Get the response
        resp = self.irc_socket.recv(2040).decode("UTF-8")

        if resp.find("PING :") != -1:
            return resp

        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        if not "PRIVMSG" in resp \
                or not self.channel in resp \
                or not self.botnick in resp:
            return None

        return resp


def func_hello(irc=None, text=""):
    if irc is not None and text:
        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        irc.send('Hello %s, the time is %s now:' % (text.split('!')[0].strip(':'), str(datetime.datetime.now())))

def main():
    irc = IRC.getInstance()

    func_listener = {
        'hello': func_hello,
    }

    irc.addFunctions(func_listener)

if __name__ == "__main__":
    main()
