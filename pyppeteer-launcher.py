from pyppeteer.launcher import Launcher
import subprocess

launcher = Launcher(executablePath='google-chrome')
cmd = launcher.cmd
cmd.append('--remote-debugging-port=9222')
subprocess.run(cmd)

