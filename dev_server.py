import os
import random
import shutil

from main import create_app, db

prometheus_dir = "var/prometheus"
os.environ["PROMETHEUS_MULTIPROC_DIR"] = prometheus_dir

if os.path.exists(prometheus_dir):
    shutil.rmtree(prometheus_dir, True)
if not os.path.exists(prometheus_dir):
    os.mkdir(prometheus_dir)

app = create_app(dev_server=True)
# Prevent DB connections and random numbers being shared
ppid = os.getpid()


@app.before_request
def fix_shared_state():
    if os.getpid() != ppid:
        db.engine.dispose()
        random.seed()


import prometheus_client.multiprocess


@app.after_request
def prometheus_cleanup(response):
    # this keeps livesum and liveall accurate
    # other metrics will hang around until restart
    prometheus_client.multiprocess.mark_process_dead(os.getpid())
    return response
