#!/usr/bin/env python

import sys
sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers


import os, subprocess
import threading


import logging, logging.handlers
logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)


class KillerThread(threading.Thread):
  def __init__(self, pid, timeout, event ):
    threading.Thread.__init__(self)
    self.pid = pid
    self.timeout = timeout
    self.event = event
    self.setDaemon(True)

  def run(self):
    self.event.wait(self.timeout)
    if not self.event.is_set():
      try:
          os.killpg(os.getpgid(self.pid), signal.SIGTERM)
      except OSError, e:
        #This is raised if the process has already completed
        pass


class MiscUtils(ZtpHelpers):
    def __init__(self,
             syslog_file=None,
             syslog_server=None,
             syslog_port=None):

    super(MiscUtils, self).__init__(syslog_file=syslog_file,
                                    syslog_server=syslog_server,
                                    syslog_port=syslog_port)

    def valid_path(self, file_path):
        return os.path.isfile(file_path)


    def run_bash_timed(self, cmd=None, timeout=5, vrf="global-vrf", pid=1):
        event = threading.Event()

        with open(self.get_netns_path(nsname=vrf,nspid=pid)) as fd:
            self.setns(fd, CLONE_NEWNET)

            if self.debug:
                self.logger.debug("bash cmd being run: "+cmd)

            if cmd is not None:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, preexec_fn=os.setsid)
                killer = KillerThread(process.pid, timeout, event)
                killer.start()
                out, err = process.communicate()
                event.set()
                killer.join()

                if self.debug:
                    self.logger.debug("output: "+out)
                    self.logger.debug("error: "+err)
            else:
                self.syslogger.info("No bash command provided")
                return {"status" : 1, "output" : "", "error" : "No bash command provided"}

            status = process.returncode
            return {"status" : status, "output" : out, "error" : err}

    def run_bash(self, cmd=None, vrf="global-vrf", pid=1):
        """User defined method in Child Class
           Wrapper method for basic subprocess.Popen to execute
           bash commands on IOS-XR.
           :param cmd: bash command to be executed in XR linux shell.
           :type cmd: str

           :return: Return a dictionary with status and output
                    { 'status': '0 or non-zero',
                      'output': 'output from bash cmd' }
           :rtype: dict
        """

        with open(self.get_netns_path(nsname=vrf,nspid=pid)) as fd:
            self.setns(fd, CLONE_NEWNET)

            if self.debug:
                self.logger.debug("bash cmd being run: "+cmd)
            ## In XR the default shell is bash, hence the name
            if cmd is not None:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
                out, err = process.communicate()
                if self.debug:
                    self.logger.debug("output: "+out)
                    self.logger.debug("error: "+err)
            else:
                self.syslogger.info("No bash command provided")
                return {"status" : 1, "output" : "", "error" : "No bash command provided"}

            status = process.returncode

            return {"status" : status, "output" : out, "error" : err}




