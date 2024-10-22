# Copyright (c) 2024 Project CHIP Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import queue
import select
import subprocess
import threading
import time
from typing import List
import fcntl # SHAO added
import os # SHAO added


class ProcessOutputCapture:
    """
    Captures stdout from a process and redirects such stdout to a given file.

    The capture serves several purposes as opposed to just reading stdout:
      - as data is received, it will get written to a separate file
      - data is accumulated in memory for later processing (does not starve/block
        the process stdout)
      - provides read timeouts for incoming data

    Use as part of a resource management block like:

    with ProcessOutputCapture("test.sh", "logs.txt") as p:
       p.send_to_program("input\n")

       while True:
           l = p.next_output_line(timeout_sec = 1)
           if not l:
               break
    """

    def __init__(self, command: List[str], output_path: str):
        # in/out/err are pipes
        self.command = command
        self.output_path = output_path
        self.output_lines = queue.Queue()
        self.process = None
        self.io_thread = None
        self.done = False # SHAO OG
        # self.done = True # SHAO mod
        # self.should_continue = True # SHAO added
        self.lock = threading.Lock() # SHAO added

    # SHAO OG modified
    # def _io_thread(self):
    #     """Reads process lines and writes them to an output file.

    #     It also sends the output lines to `self.output_lines` for later
    #     reading
    #     """
    #     out_wait = select.poll()
    #     out_wait.register(self.process.stdout, select.POLLIN | select.POLLHUP)

    #     err_wait = select.poll()
    #     err_wait.register(self.process.stderr, select.POLLIN | select.POLLHUP)

    #     # with open(self.output_path, "wt") as f: # SHAO OG
    #     with open(self.output_path, "wt", buffering=1) as f: # SHAO added line buffering, times out after checking tv-app
    #         f.write("PROCESS START: %s\n" % time.ctime())
    #         f.flush() # SHAO added
    #         while not self.done: # SHAO OG
    #         # while self.should_continue: # SHAO added
    #             # changes = out_wait.poll(0.1) # SHAO OG
    #             changes = out_wait.poll(0.0001) # SHAO added
    #             if changes: # SHAO OG
    #             # if changes and self.should_continue: # SHAO added
    #                 logging.info(f"SHAO curr output_path: {self.output_path}") # SHAO Added
    #                 logging.info(f"SHAO changes: {changes}, app: {self.output_path}")

    #                 out_line = self.process.stdout.readline() # SHAO OG
    #                 # out_line = self.process.stdout.read() # SHAO added
    #                 logging.info(f"SHAO out_line: {out_line}")
    #                 if not out_line:
    #                     logging.info(f"SHAO nothing in out_line; output_path: {self.output_path}") # SHAO added
    #                     # stdout closed (otherwise readline should have at least \n)
    #                     continue
    #                 logging.info(f"SHAO curr out_line: {out_line}")
    #                 f.write(out_line)
    #                 f.flush() # SHAO added
    #                 self.output_lines.put(out_line)

    #             changes = err_wait.poll(0)
    #             if changes:
    #                 err_line = self.process.stderr.readline()
    #                 if not err_line:
    #                     # stderr closed (otherwise readline should have at least \n)
    #                     continue
    #                 f.write(f"!!STDERR!! : {err_line}")
    #                 f.flush() # SHAO added

    #             # time.sleep(0.001) # SHAO added
                
    #         f.write("PROCESS END: %s\n" % time.ctime())
    #         f.flush() # SHAO added
    # # #

    def _io_thread(self):
        """Reads process lines and writes them to an output file.

        It also sends the output lines to `self.output_lines` for later
        reading
        """
        out_wait = select.poll()
        # SHAO OG 
        out_wait.register(self.process.stdout, select.POLLIN | select.POLLHUP)

        err_wait = select.poll()
        # SHAO OG
        err_wait.register(self.process.stderr, select.POLLIN | select.POLLHUP)

        # with open(self.output_path, "wt") as f: # SHAO OG
        with open(self.output_path, "wt", buffering=1) as f: # SHAO added line buffering, times out after checking tv-app
            f.write("PROCESS START: %s\n" % time.ctime())
            f.flush() # SHAO added
            while True:
                with self.lock:
                    if self.done:
                        break

                    changes = out_wait.poll(0.1) # SHAO OG
                    # changes = out_wait.poll(0.0001) # SHAO added
                    if changes: # SHAO OG
                    # if changes and self.should_continue: # SHAO added
                        logging.info(f"SHAO curr output_path: {self.output_path}") # SHAO Added
                        logging.info(f"SHAO changes: {changes}, app: {self.output_path}")

                        out_line = self.process.stdout.readline() # SHAO OG
                        # out_line = self.process.stdout.read() # SHAO added
                        logging.info(f"SHAO out_line: {out_line}; output_path: {self.output_path}")
                        if not out_line:
                            logging.info(f"SHAO nothing in out_line; output_path: {self.output_path}") # SHAO added
                            # stdout closed (otherwise readline should have at least \n)
                            continue
                        logging.info(f"SHAO curr out_line: {out_line}; output_path: {self.output_path}")
                        f.write(out_line)
                        f.flush() # SHAO added
                        self.output_lines.put(out_line)

                    changes = err_wait.poll(0)
                    if changes:
                        err_line = self.process.stderr.readline()
                        if not err_line:
                            # stderr closed (otherwise readline should have at least \n)
                            continue
                        f.write(f"!!STDERR!! : {err_line}")
                        f.flush() # SHAO added

            f.write("PROCESS END: %s\n" % time.ctime())
            f.flush() # SHAO added
    # #

    def __enter__(self):
        # SHAO added
        with self.lock:
            self.done = False
        # self.should_continue = True # SHAO added
        # self.done = False # SHAO OG
        # self.done = True # SHAO added
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, # SHAO OG
            bufsize=1, # SHAO added Line buffering -- empty queue for tv-casting-app noted, then checked tv-app, then timed out
            # universal_newlines=True # SHAO added Ensure consistent newline handling -- empty queue for tv-app noted, then timed out
        )
        self.io_thread = threading.Thread(target=self._io_thread)
        self.io_thread.start()
        # self.set_nonblocking(self.process.stdout.fileno()) # SHAO added
        # self.set_nonblocking(self.process.stderr.fileno()) # SHAO added
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        # SHAO added
        with self.lock:
            self.done = True

        # self.should_continue = False # SHAO added
        # self.done = True # SHAO OG
        if self.process:
            self.process.terminate()
            self.process.wait()

        if self.io_thread:
            self.io_thread.join()

        if exception_value:
            # When we fail because of an exception, report the entire log content
            logging.error(f"-------- START: LOG DUMP FOR {self.command!r} -----")
            with open(self.output_path, "rt") as f:
                for output_line in f.readlines():
                    logging.error(output_line.strip())
            logging.error(f"-------- END:   LOG DUMP FOR {self.command!r} -----")

    # # SHAO OG mod
    # def next_output_line(self, timeout_sec=None):
    #     """Fetch an item from the output queue, potentially with a timeout."""
    #     end_time = time.time() + (timeout_sec if timeout_sec is not None else 0)

    #     while True:
    #         try:
    #             remaining_time = end_time - time.time()
    #             if remaining_time <= 0:
    #                 logging.info("SHAO timeout reached - return None")
    #                 return None

    #             logging.info("SHAO fetching an item from the output queue") # SHAO added
    #             # return self.output_lines.get(timeout=timeout_sec) # SHAO OG
    #             return self.output_lines.get(timeout=remaining_time)
    #             # return self.output_lines.get_nowait() # SHAO added
    #             # return self.output_lines.get(block=True, timeout=timeout_sec) # SHAO added
    #         except queue.Empty:
    #             # self.done = True # SHAO added
    #             logging.error("SHAO queue is empty - continue") # SHAO added
    #             # return None
    #             continue
    # #

    # SHAO OG mod
    def next_output_line(self, timeout_sec=None):
        """Fetch an item from the output queue, potentially with a timeout."""
        end_time = time.time() + (timeout_sec if timeout_sec is not None else 0)
        sleep_duration = 0.1

        while True:
        
            remaining_time = end_time - time.time()
            if remaining_time <= 0:
                logging.info(f"SHAO timeout reached - return None; output_path: {self.output_path}")
                return None

            try:
                logging.info(f"SHAO fetching an item from the output queue; output_path: {self.output_path}") # SHAO added
                # return self.output_lines.get(timeout=timeout_sec) # SHAO OG
                # return self.output_lines.get(timeout=remaining_time)
                return self.output_lines.get_nowait() # SHAO added
                # return self.output_lines.get(block=True, timeout=timeout_sec) # SHAO added
            except queue.Empty:
                logging.error(f"SHAO queue is empty - sleep for {sleep_duration} sec; output_path: {self.output_path}") # SHAO added
                time.sleep(sleep_duration)
                sleep_duration = min(1.0, sleep_duration * 2)
    #

    # SHAO OG
    # def send_to_program(self, input_cmd):
    #     """Sends the given input command string to the program.

    #     NOTE: remember to append a `\n` for terminal applications
    #     """
    #     self.process.stdin.write(input_cmd)
    #     self.process.stdin.flush()

    # SHAO Added
    def send_to_program(self, input_cmd):
        """Sends the given input command string to the program.

        NOTE: remember to append a `\n` for terminal applications
        """
        with self.lock:
            if not self.done and self.process and self.process.stdin:
                self.process.stdin.write(input_cmd)
                self.process.stdin.flush()

    # SHAO added
    def is_done(self):
        with self.lock:
            return self.done
