import os
import socket
from flask import current_app as app


def irc_send(channel: str, message: str):
    message = f"{channel} {message}"
    irc_host = os.environ.get("IRCCAT", "")
    if not irc_host:
        return
    host, port_str = irc_host.split(":")
    port = int(port_str)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        s.sendall(message.encode() + b"\n")
        s.close()
    except socket.timeout:
        app.logger.warn("Timeout connecting to irccat")
    except socket.error as e:
        app.logger.warn("Error sending IRC message (%s): %s", message, e)
