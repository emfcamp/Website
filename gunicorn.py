import os
import shutil
import prometheus_client.multiprocess

def on_starting(server):
    prometheus_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR')

    if os.path.exists(prometheus_dir):
        shutil.rmtree(prometheus_dir)
    if not os.path.exists(prometheus_dir):
        os.mkdir(prometheus_dir)

def child_exit(server, worker):
    # this keeps livesum and liveall accurate
    # other metrics will hang around until restart
    prometheus_client.multiprocess.mark_process_dead(worker.pid)

