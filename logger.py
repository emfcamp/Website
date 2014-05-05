from flask import _request_ctx_stack
import logging

# Ansi color codes
CSI = '\x1b['
RESET = 0
BOLD = 1
BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(30, 38)
BACKGROUND = 40 - 30

def sgr(*codes):
    return CSI + ';'.join(map(str, codes)) + 'm'

# modified from http://plumberjack.blogspot.co.uk/2010/12/colorizing-logging-output-in-terminals.html
class ColorizingStreamHandler(logging.StreamHandler):
    DEBUG = sgr(BLUE)
    INFO = sgr(WHITE)
    WARNING = sgr(YELLOW)
    ERROR = sgr(RED)
    CRITICAL = sgr(RED, BOLD)
    reset = sgr(RESET)

    @property
    def is_tty(self):
        isatty = getattr(self.stream, 'isatty', None)
        return isatty and isatty()

    def emit(self, record):
        try:
            message = self.format(record)
            self.stream.write(message + '\n')
            self.flush()
        except Exception, e:
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

class ContextFormatter(logging.Formatter):
    def format(self, record):
        try:
            record.user = _request_ctx_stack.top.user.email
        except AttributeError:
            record.user = 'Anon'
        except Exception, e:
            record.user = 'Unknown'

        return logging.Formatter.format(self, record)


def setup_logging(app):
    fmt = '%(asctime)-15s %(levelname)s %(name)s %(user)s %(message)s'
    if app.config.get('LOG_COLOR'):
        Handler = ColorizingStreamHandler
    else:
        Handler = logging.StreamHandler

    def set_handler(logger, fmt=fmt):
        fmtr = ContextFormatter(fmt)
        hdlr = Handler()
        hdlr.setFormatter(fmtr)

        del logger.handlers[:]
        logger.addHandler(hdlr)

        return hdlr

    # replace the fallback handler
    hdlr = set_handler(logging.root)

    if not app.debug:
        logging.root.setLevel(logging.INFO)
    else:
        logging.root.setLevel(logging.DEBUG)

        if app.config.get('LOG_COLOR'):
            # Flask has already overridden its logger to change getEffectiveLevel
            # It's also cleared out any handlers, so we might as well do the same again
            if app.config.get('EXTRA_DEBUG_HANDLER'):
                hdlr = set_handler(app.logger, app.debug_log_format)
                hdlr.setLevel(logging.DEBUG)
            else:
                del app.logger.handlers[:]

        logger = logging.getLogger('sqlalchemy.engine.base.Engine')
        logger.setLevel(logging.INFO)
        hdlr = set_handler(logger)
        if app.config.get('LOG_COLOR'):
            hdlr.INFO = sgr(GREEN)
        logger.propagate = False


