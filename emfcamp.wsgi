import site, sys, os
dir = os.path.dirname(__file__)
site.addsitedir(os.path.join(dir, './env/lib/python2.6/site-packages'))
sys.path.insert(0, dir)
from main import app as application
