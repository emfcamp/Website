from enum import Enum
import logging
import os


class AnsiColors(Enum):
    RESET = 0
    BOLD = 1
    BLACK = 30
    RED = 31
    GREEN = 32
    YELLOW = 33
    BLUE = 34
    MAGENTA = 35
    CYAN = 36
    WHITE = 37
    BACKGROUND = 40 - 30

    CSI = "\x1b["

    @classmethod
    def sgr(cls, *codes):
        return (
            AnsiColors.CSI.value
            + ";".join([str(AnsiColors[c].value) for c in codes])
            + "m"
        )


# modified from http://plumberjack.blogspot.co.uk/2010/12/colorizing-logging-output-in-terminals.html


class ColorizingStreamHandler(logging.StreamHandler):
    DEFAULT_COLORS = {
        "DEBUG": "BLUE",
        "WARNING": "YELLOW",
        "ERROR": "RED",
        "CRITICAL": ["RED", "BOLD"],
    }

    def __init__(self, stream=None, colors=None):
        super().__init__(stream)

        if colors is None:
            colors = {}
        colors = dict(**self.DEFAULT_COLORS, **colors)
        self.colors = {}
        for k, v in colors.items():
            if not isinstance(v, (list, tuple)):
                v = [v]
            self.colors[k] = AnsiColors.sgr(*v)

        self.should_colorize = self.is_tty or os.getenv("COLORIZE_LOGS") == "always"

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
        color = self.colors.get(record.levelname)
        if color:
            lines = message.splitlines()
            lines_colorized = [color + line + AnsiColors.sgr("RESET") for line in lines]
            message = "\n".join(lines_colorized)
        return message

    def format(self, record):
        message = logging.StreamHandler.format(self, record)
        if self.should_colorize:
            message = self.colorize(message, record)
        return message


def mail_logging(message, app):
    if app.config.get("MAIL_SUPPRESS_SEND"):
        title = "WOULD SEND MAIL"
    else:
        title = "SENDING_MAIL"
    msg = f"""
+++++ {title} +++++
TO:  {message.recipients}
FROM:  {message.sender}
SUBJECT:  {message.subject}
---------
{message.body}
++++++++++
    """
    app.logger.info(msg)
