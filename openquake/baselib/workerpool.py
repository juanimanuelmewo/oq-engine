import os
import sys
import signal
import socket
import subprocess
import multiprocessing
from openquake.baselib import zeromq as z, parallel as p


def streamer(task_in_url, task_out_url):
    """A streamer thread for the zmq workers"""
    try:
        z.zmq.proxy(z.bind(task_in_url, z.zmq.PULL),
                    z.bind(task_out_url, z.zmq.PUSH))
    except (KeyboardInterrupt, z.zmq.ZMQError):
        pass


def _starmap(func, iterargs, task_in_url, receiver_url):
    # called by parallel.Starmap; should not be used directly
    with z.Socket(receiver_url, z.zmq.PULL, 'bind') as receiver, \
            z.Socket(task_in_url, z.zmq.PUSH, 'connect') as sender:
        n = 0
        for args in iterargs:
            # args[-1] is a Monitor instance
            args[-1].backurl = receiver.true_end_point
            sender.send((func, args))
            n += 1
        yield n
        for _ in range(n):
            # receive n responses for the n requests sent
            yield receiver.zsocket.recv_pyobj()


class WorkerMaster(object):
    """
    :param frontend_url: url where to send the tasks
    :param task_out_url: url with a range of ports to receive the results
    :param ctrl_port: port on which the worker pools listen
    :param host_cores: names of the remote hosts and number of cores
    :param remote_python: path of the Python executable on the remote hosts
    """
    def __init__(self, task_in_url, task_out_url,
                 ctrl_port, host_cores, remote_python=None):
        self.task_in_url = task_in_url
        self.task_out_url = task_out_url
        self.ctrl_port = int(ctrl_port)
        self.host_cores = [hc.split() for hc in host_cores.split(',')]
        self.remote_python = remote_python or sys.executable

    def status(self, host=None):
        """
        :returns: a list of pairs (hostname, 'running'|'not-running')
        """
        if host is None:
            host_cores = self.host_cores
        else:
            host_cores = [hc for hc in self.host_cores if hc[0] == host]
        lst = []
        for host, _ in host_cores:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                err = sock.connect_ex((host, self.ctrl_port))
            finally:
                sock.close()
            lst.append((host, 'not-running' if err else 'running'))
        return lst

    def start(self):
        """
        Start multiple workerpools, possibly on remote servers via ssh
        """
        for host, cores in self.host_cores:
            if self.status(host)[0][1] == 'running':
                print('%s already running' % host)
                continue
            ctrl_url = 'tcp://%s:%s' % (host, self.ctrl_port)

            if host == '127.0.0.1':  # localhost
                args = [sys.executable]
            else:
                args = ['ssh', host, self.remote_python]
            args += ['-m', 'openquake.baselib.workerpool',
                     ctrl_url, self.task_out_url, cores]
            print('starting ' + ' '.join(args))
            subprocess.Popen(args)
        return '%s started' % ctrl_url

    def stop(self):
        """
        Send a "stop" command to all worker pools
        """
        for host, _ in self.host_cores:
            if self.status(host)[0][1] == 'not-running':
                print('%s not running' % host)
                continue
            ctrl_url = 'tcp://%s:%s' % (host, self.ctrl_port)
            with z.Socket(ctrl_url, z.zmq.REQ, 'connect') as sock:
                print(sock.send('stop'))
        return 'stopped'

    def kill(self):
        """
        Send a "kill" command to all worker pools
        """
        for host, _ in self.host_cores:
            if self.status(host)[0][1] == 'not-running':
                print('%s not running' % host)
                continue
            ctrl_url = 'tcp://%s:%s' % (host, self.ctrl_port)
            with z.Socket(ctrl_url, z.zmq.REQ, 'connect') as sock:
                print(sock.send('kill'))
        return 'killed'


class WorkerPool(object):
    """
    A pool of workers accepting the command 'stop' and 'kill' and reading
    tasks to perform from the task_out_url.

    :param ctrl_url: zmq address of the control socket
    :param task_out_url: zmq address of the task streamer
    :param num_workers: a string with the number of workers (or '-1')
    """
    def __init__(self, ctrl_url, task_out_url, num_workers='-1'):
        self.ctrl_url = ctrl_url
        self.task_out_url = task_out_url
        self.num_workers = (multiprocessing.cpu_count()
                            if num_workers == '-1' else int(num_workers))
        self.pid = os.getpid()

    def worker(self, sock):
        p.setproctitle('oq worker')
        for cmd, args in sock:
            backurl = args[-1].backurl  # attached to the monitor
            with z.Socket(backurl, z.zmq.PUSH, 'connect') as s:
                s.send(p.safely_call(cmd, args))

    def start(self):
        p.setproctitle('oq workerpool')
        # start workers
        self.workers = []
        for _ in range(self.num_workers):
            sock = z.Socket(self.task_out_url, z.zmq.PULL, 'connect')
            proc = multiprocessing.Process(target=self.worker, args=(sock,))
            proc.start()
            sock.pid = proc.pid
            self.workers.append(sock)

        # start control loop accepting the commands stop and kill
        ctrlsock = z.Socket(self.ctrl_url, z.zmq.REP, 'bind')
        for cmd in ctrlsock:
            if cmd in ('stop', 'kill'):
                msg = getattr(self, cmd)()
                ctrlsock.send(msg)
                break
            elif cmd == 'getpid':
                ctrlsock.send(self.pid)

    def stop(self):
        for sock in self.workers:
            os.kill(sock.pid, signal.SIGINT)
        return 'WorkerPool %s stopped' % self.ctrl_url

    def kill(self):
        for sock in self.workers:
            os.kill(sock.pid, signal.SIGTERM)
        return 'WorkerPool %s killed' % self.ctrl_url


if __name__ == '__main__':
    ctrl_url, task_out_url, num_workers = sys.argv[1:]
    WorkerPool(ctrl_url, task_out_url, num_workers).start()
