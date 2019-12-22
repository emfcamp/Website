import logging

# Ansi color codes
CSI = "\x1b["
RESET = 0
BOLD = 1
BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(30, 38)
BACKGROUND = 40 - 30


def sgr(*codes):
    return CSI + ";".join(map(str, codes)) + "m"


# modified from http://plumberjack.blogspot.co.uk/2010/12/colorizing-logging-output-in-terminals.html
class ColorizingStreamHandler(logging.StreamHandler):
    DEBUG = sgr(BLUE)
    WARNING = sgr(YELLOW)
    ERROR = sgr(RED)
    CRITICAL = sgr(RED, BOLD)
    reset = sgr(RESET)

    @property
    def is_tty(self):
        isatty = getattr(self.stream, "isatty", None)
        return isatty and isatty()

    def emit(self, record):
        try:
            message = self.format(record)
            self.stream.write(message + "\n")
            self.flush()
        except Exception:
            self.handleError(record)

    def colorize(self, message, record):
        color = getattr(self, record.levelname, None)
        if color:
            message = color + message + self.reset
        return message

    def format(self, record):
        message = logging.StreamHandler.format(self, record)
        if self.is_tty:
            message = self.colorize(message, record)
        return message


class GreenStreamHandler(ColorizingStreamHandler):
    INFO = sgr(GREEN)


def mail_logging(message, app):
    msg = u"""
+++++ SENDING MAIL +++++
TO:  {0.recipients}
FROM:  {0.sender}
SUBJECT:  {0.subject}
---------
{0.body}
++++++++++
    """.format(
        message
    )
    app.logger.info(msg)
