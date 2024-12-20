#!/usr/bin/env python

from __future__ import print_function

import argparse
import multiprocessing
import json
import os
from pprint import pprint
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class Client(object):
    def __init__(self, name, config):
        self.config = config
        self.name = name
        self.json_output = config.get('json', False)

    @property
    def command(self):
        cmdline = ['iperf']

        for key, value in self.config.iteritems():
            if type(key) == 'bool':
                cmdline.append('--{}'.format(key))
            else:
                cmdline.append('--{} {}'.format(key, value))
        return ' '.join(cmdline)

    def run(self, results):
        eprint('[SET {name}] starting iperf3 transfer to {config[client]}:{config[port]}'.format(config=self.config, name=self.name))
        try:
            output = subprocess.check_output(self.command, shell=True)
        except subprocess.CalledProcessError as e:
            output = e.output
        eprint('[SET {name}] finished iperf3 transfer to {config[client]}:{config[port]}'.format(config=self.config, name=self.name))
        if self.json_output:
            output = json.loads(output)
        results.append(output)
        return output

class IperfStream(object):
    def __init__(self, set_name, stream_index, client_configs):
        self.set_name = set_name
        self.stream_index = stream_index
        self.clients = []
        self.client_procs = []

        for client_config in client_configs:
            self.clients.append(Client(set_name, config=client_config))

    def run(self):
        results = manager.list()

        eprint("[SET {}] starting stream {} with {} clients".format(self.set_name, self.stream_index, len(self.clients)))
        for client in self.clients:
           client_proc = multiprocessing.Process(target=client.run, args=(results,))
           client_proc.start()
           self.client_procs.append(client_proc)

        for client_proc in self.client_procs:
            client_proc.join()
        eprint("[SET {}] finished stream {} with {} clients".format(self.set_name, self.stream_index, len(self.clients)))

        return results._getvalue()

class IperfSet(object):
    def __init__(self, config):
        self.config = config
        self.name = self.config.get('name')
        self.wait = self.config.get('wait')
        self.streams = []

        for stream_index, stream_config in enumerate(self.config['streams'], 1):
            stream = IperfStream(self.name, stream_index, stream_config)
            self.streams.append(stream)

    def run(self, results):
        stream_results = []

        for stream in self.streams:
            stream_results.append(stream.run())

        results.append({self.name: stream_results})

class Runner(object):
    def __init__(self, config):
        self.config = config
        self.set_procs = []
        self.sets = []

        self.results = manager.list()

        for set_config in config:
            self.sets.append(IperfSet(set_config))

        self.sets = sorted(self.sets, key=lambda x: x.wait)

    def _start_set(self, set_):
        set_proc = multiprocessing.Process(target=set_.run, args=(self.results,))
        set_proc.start()
        self.set_procs.append(set_proc)

    def run(self):
        time_count = 0
        current_set_index = 0

        while current_set_index != len(self.sets):
            current_set = self.sets[current_set_index]
            time.sleep(0.01)
            time_count += 0.01
            if time_count >= current_set.wait:
                self._start_set(current_set)
                current_set_index += 1
            else:
                continue

        for set_proc in self.set_procs:
            set_proc.join()

        return self.results

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('config_file', metavar='config')
    parser.add_argument('-o', '--output-file', default=None)
    parser.add_argument('-w', '--work-dir', default='/tmp')
    parser.add_argument('-t', '--wait', type=int)
    parser.add_argument('-n', '--hostname', default=None)
    return parser.parse_args()

def get_config(config_file):
    tempdir = tempfile.mkdtemp()
    try:
        with tarfile.open(config_file) as tar:
            print("extracting tar to", tempdir)
            tar.extractall(path=tempdir)
    except Exception as e:
        print("Error extracting archive", e)

    try:
        with open(os.path.join(tempdir, 'traffic-sets.json')) as fd:
            config = json.load(fd)
            return config
    except Exception as e:
        print("Error parsing config file", e)
        raise

def main():
    args = parse_args()

    config = get_config(args.config_file)

    global manager
    manager = multiprocessing.Manager()

    if args.wait:
        time.sleep(args.wait)

    if args.hostname:
        config = config[args.hostname]

    runner = Runner(config)
    results = runner.run()

    if args.output_file is not None:
        with open(args.output_file, 'w') as fd:
            json.dump(results._getvalue(), fd, indent=4)
    else:
        pprint(results._getvalue())

def main2():
    args = parse_args()
    data = get_config(args.config_file)

    if args.hostname:
        data = data[args.hostname]

    # TODO: Fix sleep wait time to be relative instead of absolute
    script_path = os.path.join(args.work_dir, 'script')
    results_path = os.path.join(args.work_dir, 'results')
    with open(script_path, 'w') as fd:
        if args.wait:
            fd.write('sleep {}\n'.format(args.wait))
        fd.write('date +%s%N\n')
        for stream_set in data:
            streams = stream_set['streams']
            wait = stream_set.get('wait')
            if wait:
		pass
            #fd.write('sleep {}\n'.format(wait))
            #fd.write('sleep 0.005\n')
            for stream in streams:
                for client in stream:
                    command = 'iperf --client {client} --len {len} --num {num} --port {port} &'.format(**client)
                    fd.write(command + '\n')
                fd.write('wait\n')
       	fd.write('date +%s%N\n')
    subprocess.call("/usr/bin/time -v bash {} > {} 2>&1".format(script_path, results_path), shell=True)

if __name__ == '__main__':
    main2()
