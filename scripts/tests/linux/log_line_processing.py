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
        self.done = False
        self.lock = threading.Lock() # SHAO added

    def _io_thread(self):
        """Reads process lines and writes them to an output file.

        It also sends the output lines to `self.output_lines` for later
        reading
        """
        out_wait = select.poll()
        out_wait.register(self.process.stdout, select.POLLIN | select.POLLHUP)

        err_wait = select.poll()
        err_wait.register(self.process.stderr, select.POLLIN | select.POLLHUP)

        # with open(self.output_path, "wt") as f: # SHAO OG
        # SHAO added
        with open(self.output_path, "wt", buffering=1) as f:
        # SHAO Added^
            f.write("PROCESS START: %s\n" % time.ctime())
            f.flush() # SHAO added
            # while not self.done: # SHAO OG
            # while not self.done and self.poll_io_thread: # SHAO added
            # SHAO ADDED
            while True:
                with self.lock:
                    if self.done:
                        break
            # SHAO ADDED^
                # SHAO below should shift left to return to original state
                    changes = out_wait.poll(0.001)
                    if changes:

                        # logging.info(f"SHAO2 changes available after polling to write to {self.output_path}")

                        out_line = self.process.stdout.readline()

                        # logging.info(f"SHAO2 after readline; self.output_path: {self.output_path}")
                        # if not out_line: # SHAO OG
                        if not out_line or out_line == '\n': # SHAO2 mod
                            # logging.info("SHAO2 nothing in out_line")
                            # stdout closed (otherwise readline should have at least \n)
                            continue
                        # logging.info(f"SHAO2 before f.write(out_line): {out_line}")
                        f.write(out_line)
                        f.flush() # SHAO added
                        self.output_lines.put(out_line)

                    changes = err_wait.poll(0)
                    if changes:
                        # logging.error(f"SHAO2 not expecting to be here with changes: {changes}")
                        err_line = self.process.stderr.readline()
                        # if not err_line: # SHAO OG
                        if not err_line or err_line == '\n': # SHAO2 mod
                            # stderr closed (otherwise readline should have at least \n)
                            continue
                        f.write(f"!!STDERR!! : x{err_line}x")
                        f.flush()
                        # SHAO added
                # SHAO ^
            f.write("PROCESS END: %s\n" % time.ctime())
            f.flush() # SHAO added

    def __enter__(self):
        # self.done = False # SHAO OG
        # SHAO added
        with self.lock:
            self.done = False
            # self.poll_io_thread = True # SHAO added
        # SHAO ^
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1, # SHAO added
        )
        self.io_thread = threading.Thread(target=self._io_thread)
        self.io_thread.start()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        # self.done = True # SHAO OG
        # SHAO added
        with self.lock:
            self.done = True
        # SHAO ^
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

    # SHAO OG
    # def next_output_line(self, timeout_sec=None):
    #     """Fetch an item from the output queue, potentially with a timeout."""
    #     try:
    #         logging.info(f"SHAO fetch an item from the queue; output_path: {self.output_path}")
    #         return self.output_lines.get(timeout=timeout_sec)
    #     except queue.Empty:
    #         logging.error(f"SHAO queue is empty; output_path: {self.output_path}")
    #         return None
    # SHAO OG

    # SHAO modified
    # def next_output_line(self, timeout_sec=None):
    #     """Fetch an item from the output queue, potentially with a timeout."""
    #     while not f.output_lines.empty():
    #         current_time = time.time()
    #         if current_time - self.last_processed_time < self.throttle_interval:
    #             time.sleep(self.throttle_interval - (current_time - self.last_processed_time))

    #         line = self.output_lines.get()

    #     try:
    #         logging.info(f"SHAO fetch an item from the queue; output_path: {self.output_path}")
    #         return self.output_lines.get(timeout=timeout_sec)
    #     except queue.Empty:
    #         logging.error(f"SHAO queue is empty; output_path: {self.output_path}")
    #         return None




    def next_output_line(self, timeout_sec=None):
        """Fetch an item from the output queue, potentially with a timeout."""
        end_time = time.time() + (timeout_sec if timeout_sec is not None else 0)
        sleep_duration = 1.0

        while True:
            remaining_time = end_time - time.time()
            if remaining_time <= 0:
                # logging.info(f"SHAO2 timeout reached - return None; output_path: {self.output_path}")
                return None


            # if not self.output_lines.empty():
            #     logging.info(f"SHAO2 queue is not empty, output_path: {self.output_path}")
            #     return self.output_lines.get_nowait()

            # else:
            #     logging.info(f"SHAO2 queue is empty!! Attempting to readline() from std; output_path: {self.output_path}")
            #     out_line = self.process.stdout.readline()
            #     if out_line:
            #         logging.info(f"SHAO2 putting {out_line} into the queue and output_path: {self.output_path}")
            #         self.output_lines.put(out_line)
            #         with open(self.output_path, "at", buffering=1) as f:
            #             logging.info(f"SHAO2 writing {out_line} to {self.output_path}")
            #             f.write(out_line)
            #             f.flush()

            #     continue



            # # SHAO working 2/20 times with '-u' flag'
            try: # SHAO uncomment
            # if not self.output_lines.empty(): # SHAO added for testing
                # logging.info(f"SHAO2 remaining time: {remaining_time}, getting an item from the output queue inside next_output_line; self.output_path: {self.output_path}")
                return self.output_lines.get_nowait()
            except queue.Empty: # SHAO uncomment
            # else: # SHAO added for testing
                # logging.error("SHAO2 queue is empty")

                # logging.info("SHAO2 attempting to readline()")
                out_line = self.process.stdout.readline()
                if out_line:
                    # logging.info(f"SHAO2 putting new readline() into queue: {out_line}")
                    self.output_lines.put(out_line)
                    # SHAO extra
                    with open(self.output_path, "at", buffering=1) as f:
                        # logging.info(f"SHAO2 output_path: {self.output_path}")
                        f.write(out_line)
                        f.flush()
                    #
                time.sleep(sleep_duration) # SHAO uncomment
                sleep_duration = min(20.0, sleep_duration * 2) # SHAO uncomment
            # #
















    # SHAO sorta working with 10% failure
    # def next_output_line(self, timeout_sec=None):
    #     """Fetch an item from the output queue, potentially with a timeout."""
    #     end_time = time.time() + (timeout_sec if timeout_sec is not None else 0)
    #     sleep_duration = 1.0

    #     while True:
    #         remaining_time = end_time - time.time()
    #         if remaining_time <= 0:
    #             logging.info(f"SHAO1 timeout reached - return None; output_path: {self.output_path}")
    #             return None

    #         # SHAO added
    #         # If the queue is empty, we need to read for new output line from the stdout
    #         #     If there is new output line from the stdout reading,
    #         #         We have to write this new output line to the end of the log file,
    #         #         We have to flush after writing
    #         #         We have to add this to the output queue

    #         # Retrieve the item from queue and return it

    #         # if self.output_lines.empty():
    #         #     out_line = self.process.stdout.readline()
    #         #     if out_line:
    #         #         with open(self.output_path, "at", buffering=1) as f:
    #         #             f.write(out_line)
    #         #             f.flush()
    #         #             self.output_lines.put(out_line)
    #         #     else:
    #         #         # time.sleep(sleep_duration)
    #         #         # sleep_duration = min(10.0, sleep_duration * 2)
    #         #         continue
    #         # return self.output_lines.get_nowait()


    #         # if self.output_lines.empty():
                
    #         #     with open(self.output_path, "at", buffering=1) as f:

    #         #         # while not self.done: # SHAO OG
    #         #         #     changes = out_wait.poll(0.001)
    #         #         #     if changes:
    #         #         out_line = self.process.stdout.readline()

    #         #         # logging.info("SHAO1 after readline")
    #         #         if not out_line:
    #         #             # logging.info("SHAO1 nothing in out_line")
    #         #             # stdout closed (otherwise readline should have at least \n)
    #         #             continue
    #         #         # logging.info(f"SHAO1 before f.write(out_line): {out_line}")
    #         #         f.write(out_line)
    #         #         f.flush() # SHAO added
    #         #         self.output_lines.put(out_line)

    #         #             # changes = err_wait.poll(0)
    #         #             # if changes:
    #         #             #     # logging.error(f"SHAO1 not expecting to be here with changes: {changes}")
    #         #             #     err_line = self.process.stderr.readline()
    #         #             #     if not err_line:
    #         #             #         # stderr closed (otherwise readline should have at least \n)
    #         #             #         continue
    #         #             #     f.write(f"!!STDERR!! : {err_line}")
    #         #             #     f.flush()

    #         #     return self.output_lines.get_nowait()
                

    #         # SHAO working 2/20 times with '-u' flag'
    #         try: # SHAO uncomment
    #         # if not self.output_lines.empty(): # SHAO added for testing
    #             logging.info(f"SHAO1 remaining time: {remaining_time}, getting an item from the output queue inside next_output_line; self.output_path: {self.output_path}")
    #             return self.output_lines.get_nowait()
    #         except queue.Empty: # SHAO uncomment
    #         # else: # SHAO added for testing
    #             logging.error("SHAO1 queue is empty")

    #             logging.info("SHAO1 attempting to readline()")
    #             out_line = self.process.stdout.readline()
    #             if out_line:
    #                 logging.info(f"SHAO1 putting new readline() into queue: {out_line}")
    #                 self.output_lines.put(out_line)
    #                 # SHAO extra
    #                 with open(self.output_path, "at", buffering=1) as f:
    #                     logging.info(f"SHAO1 output_path: {self.output_path}")
    #                     f.write(out_line)
    #                     f.flush()
    #                 #
    #             time.sleep(sleep_duration) # SHAO uncomment
    #             sleep_duration = min(20.0, sleep_duration * 2) # SHAO uncomment
    #         #













    # SHAO modified -- improvement
    # def next_output_line(self, timeout_sec=None):
    #     """Fetch an item from the output queue, potentially with a timeout."""
    #     end_time = time.time() + (timeout_sec if timeout_sec is not None else 0)
    #     sleep_duration = 1.0

    #     while True:
    #         remaining_time = end_time - time.time()
    #         if remaining_time <= 0:
    #             # logging.info(f"SHAO1 timeout reached - return None; output_path: {self.output_path}")
    #             return None

    #         # if self.output_lines.empty():
    #         #     self._io_thread()
    #         #     return self.output_lines.get_nowait()

                

    #         try:
    #             # logging.info(f"SHAO1 remaining time: {remaining_time}, getting an item from the output queue inside next_output_line; self.output_path: {self.output_path}")
    #             return self.output_lines.get_nowait()
    #         except queue.Empty:
    #             # logging.error("SHAO1 queue is empty")

    #             # logging.info("SHAO1 attempting to readline()")
    #             out_line = self.process.stdout.readline()
    #             if out_line:
    #                 # logging.info(f"SHAO1 putting new readline() into queue: {out_line}")
    #                 self.output_lines.put(out_line)
    #             time.sleep(sleep_duration)
    #             sleep_duration = min(10.0, sleep_duration * 2)
    #             # self._io_thread()





    # SHAO OG
    # def send_to_program(self, input_cmd):
    #     """Sends the given input command string to the program.

    #     NOTE: remember to append a `\n` for terminal applications
    #     """
    #     self.process.stdin.write(input_cmd)
    #     self.process.stdin.flush()

    # SHAO modified
    def send_to_program(self, input_cmd):
        """Sends the given input command string to the program.

        NOTE: remember to append a `\n` for terminal applications
        """
        with self.lock:
            if not self.done and self.process and self.process.stdin:
                self.process.stdin.write(input_cmd)
                self.process.stdin.flush()
                # time.sleep(0.1) # SHAO added

    # SHAO added
    # Change to done
    # def set_to_stop_polling(self):
        # self.done = True
        # self.poll_io_thread = False

    # def set_to_continue_polling(self):
        # self.done = False
        # self.poll_io_thread = True
    #
