#!/usr/bin/env python

from pyppeteer.launcher import Launcher
import subprocess
import shutil
import os
import tempfile

"""
Start Headless Chrome on a well-known port for automation.

Useful if Chrome is slow to start, or for debugging.
"""

chrome_dir = 'var/pyppeteer'
if os.path.exists(chrome_dir):
    shutil.rmtree(chrome_dir, True)
if not os.path.exists(chrome_dir):
    os.mkdir(chrome_dir)

tmp_chrome_dir = tempfile.mkdtemp(dir=chrome_dir)
launcher = Launcher(executablePath='google-chrome', userDataDir=tmp_chrome_dir)
cmd = launcher.cmd
cmd.append('--remote-debugging-port=9222')
print(subprocess.list2cmdline(cmd))
subprocess.run(cmd)

