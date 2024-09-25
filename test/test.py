from pprint import pprint
from jupyter_client.consoleapp import JupyterConsoleApp

pprint("TEST")


class MyKernelApp(JupyterConsoleApp):
    def __init__(self, connection_file, runtime_dir):
        self._dispatching = False
        self.existing = connection_file
        self.runtime_dir = runtime_dir
        self.initialize()


app = MyKernelApp("connection.json", "/tmp")
kc = app.kernel_client
kc.execute("print 'hello'")
msg = kc.iopub_channel.get_msg(block=True, timeout=1)
pprint(msg)