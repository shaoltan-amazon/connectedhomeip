#!/usr/bin/env -S python3 -B

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

import pdb # SHAO debug

import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import List, Optional, TextIO, Tuple, Union

import click


"""
This test script can be used to automate the validation between the Linux tv-casting-app and the Linux tv-app.
We do this by defining a dictionary for called the test sequence where the keys will be the name of the test step 
and the values will contain which subprocess we should send the input command or parse for the output string(s) and 
within what time (in sec).
"""


# Configure logging format.
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

# The maximum amount of time to wait for the Linux tv-app to start before timeout.
TV_APP_MAX_START_WAIT_SEC = 2

DEFAULT_TIMEOUT_SEC = 10 # SHAO

# File names of logs for the Linux tv-casting-app and the Linux tv-app.
LINUX_TV_APP_LOGS = 'Linux-tv-app-logs.txt'
LINUX_TV_CASTING_APP_LOGS = 'Linux-tv-casting-app-logs.txt'

# Values that identify the Linux tv-app and are noted in the 'Device Configuration' in the Linux tv-app output
# as well as under the 'Discovered Commissioner' details in the Linux tv-casting-app output.
VENDOR_ID = 0xFFF1   # Spec 7.20.2.1 MEI code: test vendor IDs are 0xFFF1 to 0xFFF4
PRODUCT_ID = 0x8001  # Test product id
DEVICE_TYPE_CASTING_VIDEO_PLAYER = 0x23    # Device type library 10.3: Casting Video Player

# Values to verify the subscription state against from the `ReportDataMessage` in the Linux tv-casting-app output.
CLUSTER_MEDIA_PLAYBACK = '0x506'  # Application Cluster Spec 6.10.3 Cluster ID: Media Playback
ATTRIBUTE_CURRENT_PLAYBACK_STATE = '0x0000_0000'  # Application Cluster Spec 6.10.6 Attribute ID: Current State of Playback

# valid_discovered_commissioner_number_placeholder = '-1'
# valid_discovered_commissioner_number = ''


class ProcessManager:
    """A context manager for managing subprocesses.

    This class provides a context manager for safely starting and stopping a subprocess.
    """

    def __init__(self, command: List[str], stdin, stdout, stderr):
        self.command = command
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def __enter__(self):
        self.process = subprocess.Popen(self.command, stdin=self.stdin, stdout=self.stdout, stderr=self.stderr, text=True)
        return self.process

    def __exit__(self, exception_type, exception_value, traceback):
        self.process.terminate()
        self.process.wait()


class LogValueExtractor:
    """A utility class for extracting values from log lines.

    This class provides a centralized way to extract values from log lines and manage the error handling and logging process.
    """

    def __init__(self, log_paths: List[str]):
        self.log_paths = log_paths

    def extract_from(self, line: str, value_name: str):
        if value_name in line:
            try:
                return extract_value_from_string(line, value_name, self.log_paths)
            except ValueError:
                logging.error(f'Failed to extract `{value_name}` value from line: {line}')
                handle_casting_failure(self.log_paths)
        return None


# class String:

#     def __init__(self, value: str):
#         self._value = value
    
#     @property
#     def value(self):
#         return self._value
    
#     @value.setter
#     def value(self, value: str):
#         self._value = value
    
#     def __str__(self):
#         return str(self._value)

#     def __repr__(self):
#         return str(self._value)

#     def compare(self, value: str):
#         return self._value == value



# valid_discovered_commissioner_number_placeholder = String(-1)
valid_discovered_commissioner_number_placeholder = -1

class Step:
    """A class to represent a step in a test sequence that we want to validate.

    This class represents a step in a test sequence and contained the properties of the step.
    """
    # def __init__(self, subprocess=None, timeout_sec=None, output_msg=None, input_cmd=None):
    #     self.subprocess = subprocess
    #     self.timeout_sec = timeout_sec if input_cmd is None else None
    #     self.output_msg = output_msg if input_cmd is None else None
    #     self.input_cmd = input_cmd if output_msg is None else None

    def __init__(self, subprocess=None, timeout_sec=DEFAULT_TIMEOUT_SEC, output_msg=None, input_cmd=None):
        self.subprocess = subprocess
        self.timeout_sec = timeout_sec if input_cmd is None else None
        self.output_msg = output_msg if input_cmd is None else None
        self.input_cmd = input_cmd if output_msg is None else None




# A test sequence consists of test steps. Each step defines whether which subprocess we want to parse for output string(s) or send input command.
# sequence_general = {
#     'validate_started_commissioner': Step('tv-app', TV_APP_MAX_START_WAIT_SEC, ['Started commissioner'], None),
#     'validate_discovered_commissioner': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Discovered Commissioner #', f'Vendor ID: {VENDOR_ID}', f'Product ID: {PRODUCT_ID}', f'Device Type: {DEVICE_TYPE_CASTING_VIDEO_PLAYER}', 'Supports Commissioner Generated Passcode: true'], None),
#     'validate_example_cast_request': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Example: cast request 0'], None),
#     # 'send_cast_request_cmd': Step('tv-casting-app', None, None, f'cast request {discovered_commissioner_number_placeholder}\n'),
#     # 'send_cast_request_cmd': Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number}\n'),
#     'send_cast_request_cmd': Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number_placeholder}\n'),
#     'validate_identification_declaration_msg_tv_casting_app': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
#     'validate_identification_declaration_msg_tv_app': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
#     'validate_casting_request_prompt': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['PROMPT USER: Test TV casting app is requesting permission to cast to this TV, approve?'], None),
#     'validate_example_controller_ux_ok_cmd': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Via Shell Enter: controller ux ok|cancel'], None),
#     'send_contoller_ux_ok_cmd': Step('tv-app', None, None, 'controller ux ok\n'),
#     'validate_secure_pairing_success': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Secure Pairing Success'], None),
#     'validate_commissioning_success_tv_casting_app': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Commissioning completed successfully'], None),
#     'validate_commissioning_success_tv_app': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['------PROMPT USER: commissioning success'], None),
#     'validate_report_data_msg': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['ReportDataMessage =', f'Cluster = {CLUSTER_MEDIA_PLAYBACK}', f'Attribute = {ATTRIBUTE_CURRENT_PLAYBACK_STATE}', 'InteractionModelRevision =', '}'], None),
#     'validate_launchURL': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['ContentLauncherManager::HandleLaunchUrl TEST CASE ContentURL=https://www.test.com/videoid DisplayString=Test video'], None),
#     'validate_invoke_response_msg': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['InvokeResponseMessage =', 'exampleData', 'InteractionModelRevision =', '},'], None)
# }

# sequence_general = [
#     Step('tv-app', TV_APP_MAX_START_WAIT_SEC, ['Started commissioner'], None),
#     Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Discovered Commissioner #', f'Vendor ID: {VENDOR_ID}', f'Product ID: {PRODUCT_ID}', f'Device Type: {DEVICE_TYPE_CASTING_VIDEO_PLAYER}', 'Supports Commissioner Generated Passcode: true'], None),
#     Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Example: cast request 0'], None),
#     # Step('tv-casting-app', None, None, f'cast request {discovered_commissioner_number_placeholder}\n'),
#     # Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number}\n'),
#     Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number_placeholder}\n'),
#     Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
#     Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
#     Step('tv-app', DEFAULT_TIMEOUT_SEC, ['PROMPT USER: Test TV casting app is requesting permission to cast to this TV, approve?'], None),
#     Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Via Shell Enter: controller ux ok|cancel'], None),
#     Step('tv-app', None, None, 'controller ux ok\n'),
#     Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Secure Pairing Success'], None),
#     Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Commissioning completed successfully'], None),
#     Step('tv-app', DEFAULT_TIMEOUT_SEC, ['------PROMPT USER: commissioning success'], None),
#     Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['ReportDataMessage =', f'Cluster = {CLUSTER_MEDIA_PLAYBACK}', f'Attribute = {ATTRIBUTE_CURRENT_PLAYBACK_STATE}', 'InteractionModelRevision =', '}'], None),
#     Step('tv-app', DEFAULT_TIMEOUT_SEC, ['ContentLauncherManager::HandleLaunchUrl TEST CASE ContentURL=https://www.test.com/videoid DisplayString=Test video'], None),
#     Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['InvokeResponseMessage =', 'exampleData', 'InteractionModelRevision =', '},'], None)
# ]


sequence_general = [
    Step(subprocess='tv-app', timeout_sec=TV_APP_MAX_START_WAIT_SEC, output_msg=['Started commissioner']),
    Step(subprocess='tv-casting-app', output_msg=['Discovered Commissioner #', f'Vendor ID: {VENDOR_ID}', f'Product ID: {PRODUCT_ID}', f'Device Type: {DEVICE_TYPE_CASTING_VIDEO_PLAYER}', 'Supports Commissioner Generated Passcode: true']),
    Step(subprocess='tv-casting-app', output_msg=['Example: cast request 0']),
    # Step(subprocess='tv-casting-app', input_cmd=f'cast request {discovered_commissioner_number_placeholder}\n'),
    # Step(subprocess='tv-casting-app', input_cmd=f'cast request {valid_discovered_commissioner_number}\n'),
    Step(subprocess='tv-casting-app', input_cmd=f'cast request {valid_discovered_commissioner_number_placeholder}\n'),
    Step(subprocess='tv-casting-app', output_msg=['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End']),
    Step(subprocess='tv-app', output_msg=['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End']),
    Step(subprocess='tv-app', output_msg=['PROMPT USER: Test TV casting app is requesting permission to cast to this TV, approve?']),
    Step(subprocess='tv-app', output_msg=['Via Shell Enter: controller ux ok|cancel']),
    Step(subprocess='tv-app', input_cmd='controller ux ok\n'),
    Step(subprocess='tv-app', output_msg=['Secure Pairing Success']),
    Step(subprocess='tv-casting-app', output_msg=['Commissioning completed successfully']),
    Step(subprocess='tv-app', output_msg=['------PROMPT USER: commissioning success']),
    Step(subprocess='tv-casting-app', output_msg=['ReportDataMessage =', f'Cluster = {CLUSTER_MEDIA_PLAYBACK}', f'Attribute = {ATTRIBUTE_CURRENT_PLAYBACK_STATE}', 'InteractionModelRevision =', '}']),
    Step(subprocess='tv-app', output_msg=['ContentLauncherManager::HandleLaunchUrl TEST CASE ContentURL=https://www.test.com/videoid DisplayString=Test video']),
    Step(subprocess='tv-casting-app', output_msg=['InvokeResponseMessage =', 'exampleData', 'InteractionModelRevision =', '},'])
]


# sequence_general.append(Step('tv-app', TV_APP_MAX_START_WAIT_SEC, ['Started commissioner'], None))
# sequence_general.append(Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Discovered Commissioner #', f'Vendor ID: {VENDOR_ID}', f'Product ID: {PRODUCT_ID}', f'Device Type: {DEVICE_TYPE_CASTING_VIDEO_PLAYER}', 'Supports Commissioner Generated Passcode: true'], None))
# sequence_general.append(Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Example: cast request 0'], None))
#     # Step('tv-casting-app', None, None, f'cast request {discovered_commissioner_number_placeholder}\n'),
#     # Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number}\n'),
# sequence_general.append(Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number_placeholder}\n'))
# Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
# Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
# Step('tv-app', DEFAULT_TIMEOUT_SEC, ['PROMPT USER: Test TV casting app is requesting permission to cast to this TV, approve?'], None),
# Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Via Shell Enter: controller ux ok|cancel'], None),
# Step('tv-app', None, None, 'controller ux ok\n'),
# Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Secure Pairing Success'], None),
# Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Commissioning completed successfully'], None),
# Step('tv-app', DEFAULT_TIMEOUT_SEC, ['------PROMPT USER: commissioning success'], None),
# Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['ReportDataMessage =', f'Cluster = {CLUSTER_MEDIA_PLAYBACK}', f'Attribute = {ATTRIBUTE_CURRENT_PLAYBACK_STATE}', 'InteractionModelRevision =', '}'], None),
# Step('tv-app', DEFAULT_TIMEOUT_SEC, ['ContentLauncherManager::HandleLaunchUrl TEST CASE ContentURL=https://www.test.com/videoid DisplayString=Test video'], None),
# Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['InvokeResponseMessage =', 'exampleData', 'InteractionModelRevision =', '},'], None)




def dump_temporary_logs_to_console(log_file_path: str):
    """Dump log file to the console; log file will be removed once the function exits."""
    """Write the entire content of `log_file_path` to the console."""
    print(f'\nDumping logs from: {log_file_path}')

    with open(log_file_path, 'r') as file:
        for line in file:
            print(line.rstrip())


def handle_casting_failure(log_file_paths: List[str]):
    """Dump log files to console, exit on error."""

    for log_file_path in log_file_paths:
        try:
            dump_temporary_logs_to_console(log_file_path)
        except Exception as e:
            logging.exception(f'Failed to dump {log_file_path}: {e}')

    sys.exit(1)


# SHAO -- I don't think this function needs to be so lenghty anymore!
def extract_value_from_string(line: str, value_name: str, log_paths) -> str:
    """Extract and return value from given input string.

    Some string examples as they are received from the Linux tv-casting-app output:
    1. On 'darwin' machines:
        \x1b[0;32m[1714582264602] [77989:2286038] [SVR] Discovered Commissioner #0\x1b[0m
        The integer value to be extracted here is '0'.

    2. On 'linux' machines:
        [1716224958.576320][6906:6906] CHIP:SVR: Discovered Commissioner #0
    """
    log_line_pattern = ''
    if sys.platform == 'darwin':
        log_line_pattern = r'\x1b\[0;\d+m\[\d+\] \[\d+:\d+\] \[[A-Z]{1,3}\] (.+)\x1b\[0m'
    elif sys.platform == 'linux':
        log_line_pattern = r'\[\d+\.\d+\]\[\d+:\d+\] [A-Z]{1,4}:[A-Z]{1,3}: (.+)'

    log_line_match = re.search(log_line_pattern, line)

    if log_line_match:
        log_text_of_interest = log_line_match.group(1)

        if '#' in log_text_of_interest:
            delimiter = '#'

        return log_text_of_interest.split(delimiter)[-1].strip(' ')
    else:
        raise ValueError(f'Could not extract {value_name} from the following line: {line}')


def update_number(new_value):
    global valid_discovered_commissioner_number_placeholder # SHAO added
    print(f'SHAO entered update_number')
    print(f'current valid_discovered_commissioner_number_placeholder: {valid_discovered_commissioner_number_placeholder}')
    print(f'current sequence_general[3].input_cmd: {sequence_general[3].input_cmd}')
    valid_discovered_commissioner_number_placeholder = new_value
    print(f'after valid_discovered_commissioner_number_placeholder: {valid_discovered_commissioner_number_placeholder}')
    print(f'after sequence_general[3].input_cmd: {sequence_general[3].input_cmd}')
    

def parse_subprocess_output(tv_casting_app_info: Tuple[subprocess.Popen, TextIO], tv_app_info: Tuple[subprocess.Popen, TextIO], log_paths: List[str], step: Step):
    """Parse the output of a given subprocess and validate the output against the expected output strings."""
    global sequence_general # SHAO added
    global valid_discovered_commissioner_number_placeholder # SHAO added
    app_subprocess, app_log_file = (tv_casting_app_info if step.subprocess == 'tv-casting-app' else tv_app_info)

    start_wait_time = time.time()
    msg_block = []

    i = 0
    while i < len(step.output_msg):
        # Check if we exceeded the maximum wait time to parse for the output strings.
        if time.time() - start_wait_time > step.timeout_sec:
            logging.error(f'Did not find the expected string(s) in the {step.subprocess} subprocess within the timeout: {step.output_msg}')
            return False

        output_line = app_subprocess.stdout.readline()

        if output_line:
            app_log_file.write(output_line)
            app_log_file.flush()

            if (step.output_msg[i] in output_line):
                if 'Discovered Commissioner #' in step.output_msg[i]:
                    log_value_extractor = LogValueExtractor(log_paths)
                    valid_discovered_commissioner_number = log_value_extractor.extract_from(output_line, 'Discovered Commissioner #')
                    print(f'SHAO type(valid_discovered_commissioner_number): {type(valid_discovered_commissioner_number)}')
                    # # valid_discovered_commissioner_number = String(valid_discovered_commissioner_number)
                    # print(f'SHAO valid_discovered_commissioner_number: {valid_discovered_commissioner_number}, type(valid_discovered_commissioner_number): {type(valid_discovered_commissioner_number)}')
                    
                    # if not valid_discovered_commissioner_number_placeholder.compare(valid_discovered_commissioner_number):
                    if valid_discovered_commissioner_number_placeholder != valid_discovered_commissioner_number:
                        print('SHAO hereeeeee')
                        update_number(valid_discovered_commissioner_number)
                        # valid_discovered_commissioner_number_placeholder = String(valid_discovered_commissioner_number)
                        # print(f'SHAO valid_discovered_commissioner_number after: {valid_discovered_commissioner_number.value}')
                        print(f'SHAO valid_discovered_commissioner_number after: {valid_discovered_commissioner_number}')
                        print(f'SHAO valid_discovered_commissioner_number_placeholder after: {valid_discovered_commissioner_number_placeholder}')
                        print(f'SHAO sequence_general[3].input_cmd after: {sequence_general[3].input_cmd}')
                    # if valid_discovered_commissioner_number != valid_discovered_commissioner_number_placeholder:
                    #     print(f'SHAO valid_discovered_commissioner_number: {valid_discovered_commissioner_number}, type(valid_discovered_commissioner_number): {type(valid_discovered_commissioner_number)}')
                    #     print(f'SHAO valid_discovered_commissioner_number_placeholder: {valid_discovered_commissioner_number_placeholder}, type(valid_discovered_commissioner_number_placeholder): {type(valid_discovered_commissioner_number_placeholder)}')
                    #     print(f'SHAO sequence_general[3].input_cmd: {sequence_general[3].input_cmd}')
                    #     # valid_discovered_commissioner_number_placeholder.value = Integer(valid_discovered_commissioner_number)
                    #     sequence_general[3].input_cmd = sequence_general[3].input_cmd.format(valid_discovered_commissioner_number_placeholder = valid_discovered_commissioner_number)
                    # print(f'SHAO valid_discovered_commissioner_number after: {valid_discovered_commissioner_number}')
                    # print(f'SHAO valid_discovered_commissioner_number_placeholder after: {valid_discovered_commissioner_number_placeholder}')
                    # print(f'SHAO sequence_general[3].input_cmd after: {sequence_general[3].input_cmd}')
                    # # if valid_discovered_commissioner_number != discovered_commissioner_number_placeholder:
                    # #     sequence_general['send_cast_request_cmd'].input_cmd = f'cast request {valid_discovered_commissioner_number}\n'
                
                msg_block.append(output_line.rstrip('\n'))
                i+=1
            elif msg_block:
                msg_block.append(output_line.rstrip('\n'))
                if (step.output_msg[0] in output_line):
                    msg_block.clear()
                    msg_block.append(output_line.rstrip('\n'))
                    i = 1
            
            if i == len(step.output_msg):
                logging.info(f'Found the expected output string(s) in the {step.subprocess} subprocess:')
                for line in msg_block:
                    logging.info(line)

                return True


def write_to_subprocess(tv_casting_app_info: Tuple[subprocess.Popen, TextIO], tv_app_info: Tuple[subprocess.Popen, TextIO], step: Step):
    """Write a given input command to a given subprocess."""
    app_subprocess, app_log_file = (tv_casting_app_info if step.subprocess == 'tv-casting-app' else tv_app_info)

    global valid_discovered_commissioner_number_placeholder

    print(f'SHAO step.input_cmd: {step.input_cmd}')
    if 'cast request' in step.input_cmd:
        step.input_cmd = f'cast request {valid_discovered_commissioner_number_placeholder}\n'
        print(f'SHAO after step.input_cmd: {step.input_cmd}')

    app_subprocess.stdin.write(step.input_cmd)
    app_subprocess.stdin.flush()
    # Move to the next line otherwise we will keep entering this code block
    next_line = app_subprocess.stdout.readline()
    app_log_file.write(next_line)
    app_log_file.flush()
    next_line = next_line.rstrip('\n')

    logging.info(f'Sent `{next_line}` to the {step.subprocess} subprocess.')


@click.command()
@click.option('--tv-app-rel-path', type=str, default='out/tv-app/chip-tv-app', help='Path to the Linux tv-app executable.')
@click.option('--tv-casting-app-rel-path', type=str, default='out/tv-casting-app/chip-tv-casting-app', help='Path to the Linux tv-casting-app executable.')
def test_casting_fn(tv_app_rel_path, tv_casting_app_rel_path):
    """Test if the Linux tv-casting-app is able to discover and commission the Linux tv-app as part of casting.

    Default paths for the executables are provided but can be overridden via command line arguments.
    For example: python3 run_tv_casting_test.py --tv-app-rel-path=path/to/tv-app
                 --tv-casting-app-rel-path=path/to/tv-casting-app
    """
    # Store the log files to a temporary directory.
    with tempfile.TemporaryDirectory() as temp_dir:
        linux_tv_app_log_path = os.path.join(temp_dir, LINUX_TV_APP_LOGS)
        linux_tv_casting_app_log_path = os.path.join(temp_dir, LINUX_TV_CASTING_APP_LOGS)

        print(f'SHAO tempdir: {temp_dir}')

        with open(linux_tv_app_log_path, 'w') as linux_tv_app_log_file, open(linux_tv_casting_app_log_path, 'w') as linux_tv_casting_app_log_file:

            # Configure command options to disable stdout buffering during tests.
            disable_stdout_buffering_cmd = []
            # On Unix-like systems, use stdbuf to disable stdout buffering.
            if sys.platform == 'darwin' or sys.platform == 'linux':
                disable_stdout_buffering_cmd = ['stdbuf', '-o0', '-i0']

            tv_app_abs_path = os.path.abspath(tv_app_rel_path)
            # Run the Linux tv-app subprocess.
            with ProcessManager(disable_stdout_buffering_cmd + [tv_app_abs_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as tv_app_process:
                tv_app_info = (tv_app_process, linux_tv_app_log_file)
                # if not parse_subprocess_output(None, tv_app_info, [linux_tv_app_log_path], sequence_general['validate_started_commissioner']): # SHAO for dictionary use
                if not parse_subprocess_output(None, tv_app_info, [linux_tv_app_log_path], sequence_general[0]):
                    handle_casting_failure([linux_tv_app_log_path])

                tv_casting_app_abs_path = os.path.abspath(tv_casting_app_rel_path)
                # Run the Linux tv-casting-app subprocess.
                with ProcessManager(disable_stdout_buffering_cmd + [tv_casting_app_abs_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as tv_casting_app_process:
                    log_paths = [linux_tv_app_log_path, linux_tv_casting_app_log_path]
                    tv_casting_app_info = (tv_casting_app_process, linux_tv_casting_app_log_file)

                    # SHAO for dictionary use
                    # for step_name, step_data in sequence_general.items():
                    #     if step_name == 'started_commissioner':
                    #         continue

                    #     if step_data.output_msg:
                    #         if not parse_subprocess_output(tv_casting_app_info, tv_app_info, log_paths, step_data):
                    #             handle_casting_failure(log_paths)
                    #     elif step_data.input_cmd:
                    #         write_to_subprocess(tv_casting_app_info, tv_app_info, step_data)
                    
                    i = 1
                    while i < len(sequence_general):
                        step = sequence_general[i]
                    
                        if step.output_msg:
                            if not parse_subprocess_output(tv_casting_app_info, tv_app_info, log_paths, step):
                                handle_casting_failure(log_paths)
                        elif step.input_cmd:
                            # if 'cast request' in step.input_cmd:
                            #     step.input_cmd = f'cast request {valid_discovered_commissioner_number_placeholder}'
                            write_to_subprocess(tv_casting_app_info, tv_app_info, step)

                        i += 1


if __name__ == '__main__':

    # Start with a clean slate by removing any previously cached entries.
    os.system('rm -f /tmp/chip_*')

    # # SHAO define the variables here:
    # # A test sequence consists of test steps. Each step defines whether which subprocess we want to parse for output string(s) or send input command.
    # sequence_general = {
    #     'started_commissioner': Step('tv-app', TV_APP_MAX_START_WAIT_SEC, ['Started commissioner'], None),
    #     'discover_commissioner': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Discovered Commissioner #', f'Vendor ID: {VENDOR_ID}', f'Product ID: {PRODUCT_ID}', f'Device Type: {DEVICE_TYPE_CASTING_VIDEO_PLAYER}', 'Supports Commissioner Generated Passcode: true'], None),
    #     'example_cast_request': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Example: cast request 0'], None),
    #     # 'send_cast_request_cmd': Step('tv-casting-app', None, None, f'cast request {discovered_commissioner_number_placeholder}\n'),
    #     'send_cast_request_cmd': Step('tv-casting-app', None, None, f'cast request {valid_discovered_commissioner_number}\n'),
    #     'identification_declaration_msg_tv_casting_app': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
    #     'identification_declaration_msg_tv_app': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Identification Declaration Start', 'device Name: Test TV casting app', f'vendor id: {VENDOR_ID}', f'product id: {PRODUCT_ID}', 'Identification Declaration End'], None),
    #     'prompt_casting_request': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['PROMPT USER: Test TV casting app is requesting permission to cast to this TV, approve?'], None),
    #     'example_controller_ux_ok_cmd': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Via Shell Enter: controller ux ok|cancel'], None),
    #     'send_contoller_ux_ok_cmd': Step('tv-app', None, None, 'controller ux ok\n'),
    #     'secure_pairing_success': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['Secure Pairing Success'], None),
    #     'commissioning_success_tv_casting_app': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['Commissioning completed successfully'], None),
    #     'commissioning_success_tv_app': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['------PROMPT USER: commissioning success'], None),
    #     'report_data_msg': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['ReportDataMessage =', f'Cluster = {CLUSTER_MEDIA_PLAYBACK}', f'Attribute = {ATTRIBUTE_CURRENT_PLAYBACK_STATE}', 'InteractionModelRevision =', '}'], None),
    #     'launchURL': Step('tv-app', DEFAULT_TIMEOUT_SEC, ['ContentLauncherManager::HandleLaunchUrl TEST CASE ContentURL=https://www.test.com/videoid DisplayString=Test video'], None),
    #     'invoke_response_msg': Step('tv-casting-app', DEFAULT_TIMEOUT_SEC, ['InvokeResponseMessage =', 'exampleData', 'InteractionModelRevision =', '},'], None)
    # }

    # Test casting (discovery and commissioning) between the Linux tv-casting-app and the tv-app.
    test_casting_fn()