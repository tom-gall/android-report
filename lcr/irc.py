#!/usr/bin/env python3

# https://www.techbeamers.com/create-python-irc-bot/
# https://linuxacademy.com/blog/linux-academy/creating-an-irc-bot-with-python3/
# https://tools.ietf.org/html/rfc1459
# https://freenode.net/kb/answer/registration

import base64
import datetime
import logging
import socket
import ssl
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
        if IRC.__instance == None:
            logger.info("new instance")
            return IRC()

        logger.info("use existing instance")
        return IRC.__instance

    def __init__(self):
        """ Virtually private constructor. """

        if IRC.__instance != None:
            raise Exception("This class is a singleton!")

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

            IRC.__instance = self
            self.connect_lock = threading.Lock()
            #self.connect_lock = threading.RLock()
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
            text = self.getPingOrPRIMSG()
            for key_word, irc_func in self.getFuncions().items():
                #if resp.find('PING') != -1:
                if text and (text.find(key_word) != -1):
                    irc_func(self, text)
            time.sleep(1)

    # TODO need to be thread safe
    def addFunctions(self, func_dict={}):
        for key in func_dict.keys():
            logger.info("regiester irc function: %s" % key)
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


    def sendAndQuit(self, msgStrOrAry=None, using_sasl=True):
        if self.server is None:
            # should be only available when irc notification enabled
            return
        else:
            # maybe need a system level lock, so that the management commands
            # and the server instance could share the lock
            #with self.connect_lock:
            self.connect_lock.acquire() # OSError: [Errno 106] Transport endpoint is already connected
            self.connect(using_sasl=using_sasl)
            self.connect_lock.release() # OSError: [Errno 106] Transport endpoint is already connected

            self.send(msgStrOrAry=msgStrOrAry)
            time.sleep(3) # workaround for Ping timeout: 260 seconds
            self.quit()


    def authenticateWithASAL(self, botnick, botpass):
        # https://ircv3.net/
        # https://ircv3.net/specs/core/capability-negotiation
        # https://tools.ietf.org/search/rfc4616
        # https://en.wikipedia.org/wiki/List_of_Internet_Relay_Chat_commands#USER
        # https://tools.ietf.org/html/rfc2812
        self.sendCommand("CAP REQ :sasl")
        self.sendCommand("NICK %s" % botnick)
        self.sendCommand("USER %s 0 * :%s" % (botnick, botnick))

        if not self.wait_text("CAP * ACK :sasl"):
            logger.warn("Failed to get the correct response from server for CAP REQ :sasl")
            return False

        self.sendCommand("AUTHENTICATE PLAIN")
        if not self.wait_text("AUTHENTICATE +"):
            logger.warn("Failed to get the correct response from server for AUTHENTICATE PLAIN")
            return False

        creds = '{username}\0{username}\0{password}'.format(username=botnick, password=botpass)
        self.sendCommand('AUTHENTICATE {}'.format(base64.b64encode(creds.encode('utf8')).decode('utf8')))
        if not self.wait_text("{} :SASL authentication successful".format(botnick)):
            logger.warn("Failed to get the correct response for SASL authentication with the user of {}".format(botnick))
            return False

        self.sendCommand("CAP END")
        if not self.wait_text("001 {} :Welcome to the freenode Internet Relay Chat Network {}".format(botnick, botnick)):
            logger.warn("Failed to get the correct response for welcome for the user of {}".format(botnick))
            return False
        else:
            logger.info("Welcome, {}".format(botnick))


    def authenticate(self, botnick, botpass):
        # Perform user authentication
        self.irc_socket.send(bytes("USER " + botnick + " " + botnick +" " + botnick + " :python\n", "UTF-8"))
        logger.info("after send command USER to: " + server)
        self.irc_socket.send(bytes("NICK " + botnick + "\n", "UTF-8"))
        logger.info("after send command NICK to: " + server)
        self.irc_socket.send(bytes("NICKSERV IDENTIFY " + botpass + "\n", "UTF-8"))

        str_idenfified = "You are now identified for"
        identified = False
        sleep_time = 0
        while not identified:
            if sleep_time > 25:
                logger.info("Failed to identify for the account of %s after %d seconds" % (botnick, sleep_time))
                break
            text = self.irc_socket.recv(2040).decode("UTF-8")
            if text.find(str_idenfified) != -1:
                logger.info("found identified message")
                identified = True
            else:
                logger.debug("%d: not found identified message" % sleep_time)
                time.sleep(3)
                sleep_time = sleep_time + 3


    def join(self, channel):
        # continue to try, but the result won't be as expected
        # join the channel
        logger.info("Try to join: " + channel)
        self.irc_socket.send(bytes("JOIN " + channel + "\n", "UTF-8"))
        str_joined = ":End of /NAMES list"
        joined = False
        sleep_time = 0
        while not joined:
            if sleep_time > 120:
                logger.info("Failed to join %s " % self.channel)
                break
            text = self.get_response()
            if text.find(str_joined) != -1:
                logger.info("found joined message")
                joined = True
            else:
                logger.debug("%d not found joined message" % sleep_time)
                time.sleep(10)
                sleep_time = sleep_time + 10
        if joined:
            logger.info("joined to: " + channel)
            return True
        else:
            return False


    def connectOnly(self, server, port):
        if self.irc_socket is None:
            self.irc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if str(port) == '6697':
                self.irc_socket = ssl.wrap_socket(self.irc_socket)

        # Connect to the server
        logger.info("Connecting to: " + server)
        self.irc_socket.connect((server, int(port))) # OSError: [Errno 106] Transport endpoint is already connected

    def connectAuthenticate(self, server, port, botnick, botpass, using_sasl=False):
        self.connectOnly(server, port)
        if using_sasl:
            self.authenticateWithASAL(botnick, botpass)
        else:
            self.authenticate(botnick, botpass)


    def connectAuthenticateJoin(self, server, port, channel, botnick, botpass, using_sasl=False):
        self.connectAuthenticate(server, port, botnick, botpass, using_sasl=using_sasl)
        self.join(channel)


    def connect(self, using_sasl=False):
        self.connectAuthenticateJoin(self.server, self.port, self.channel, self.botnick, self.botpass, using_sasl=using_sasl)


    # only deal with the message to this irc nick and channel
    def getPingOrPRIMSG(self):
        resp = self.get_response()
        if resp.find("PING :") != -1:
            return resp

        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        if not "PRIVMSG" in resp \
                or not self.channel in resp \
                or not self.botnick in resp:
            return None

        return resp


    def get_response(self):
        if self.irc_socket is None:
            logger.info("RESPONSE: irc_socket is None")
            return None

        try:
            reader = getattr(self.irc_socket, 'read', self.irc_socket.recv)
            new_data = reader(2 ** 14)
        except socket.error:
            # The server hung up.
            self.disconnect("Connection reset by peer")
            return None
        if not new_data:
            # Read nothing: connection must be down.
            logger.info("Nothing read, the connection might be down")
            return None

        resp = new_data.decode("UTF-8")
        logger.debug("RESPONSE: %s" % resp)
        return resp


    def wait_text(self, target_text, timeout=10):
        wait_time = timeout
        while wait_time >= 0:
            text = self.get_response()
            if text.find(target_text) != -1:
                return True
            time.sleep(3)
            wait_time = wait_time -3
        return False


    def sendCommand(self, commandStr):
        logger.debug("send command %s" % commandStr)
        self.irc_socket.send( bytes(commandStr, "UTF-8")+ b'\r\n')


def func_hello(irc=None, text=""):
    if irc is not None and text:
        # :liuyq!liuyq@gateway/shell/linaro/x-ykpaytiswxaohqwr PRIVMSG #liuyq-test :lkft-android-bot PING
        irc.send('Hello %s, the time is %s now:' % (text.split('!')[0].strip(':'), str(datetime.datetime.now())))


def main():
    irc = IRC.getInstance()

    #func_listener = {
    #    'hello': func_hello,
    #}

    #irc.addFunctions(func_listener)
    irc.connectOnly('chat.freenode.net', 6697)
    irc.authenticateWithASAL(irc_botnick, irc_botpass)
    irc.join(irc_channel)
    irc.send(msgStrOrAry=["Hello, finally finished {}!".format(datetime.datetime.now(tz=None).isoformat())])
    irc.quit()

if __name__ == "__main__":
    main()
