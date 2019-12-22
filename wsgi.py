from werkzeug.middleware.proxy_fix import ProxyFix
from main import create_app

# ProxyFix handles the X-Forwarded-For and X-Forwarded-Proto headers
app = ProxyFix(create_app())
