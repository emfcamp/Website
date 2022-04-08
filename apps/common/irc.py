import os
import socket
from flask import current_app as app


def irc_send(message):
    if "IRCCAT" not in os.environ:
        app.logger.warn("No IRCCAT env variable?")
        return
    host, port = os.environ.get("IRCCAT").split(":")
    port = int(port)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, port))
        s.sendall(message.encode() + b"\n")
        s.close()
    except socket.error as e:
        app.logger.warn("Error sending IRC message (%s): %s", message, e)
