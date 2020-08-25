#!/usr/bin/env python

import sys
sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers

import os, posixpath, subprocess
import time, json
import threading, tempfile
from urlparse import urlparse
import signal, argparse
from functools import partial

import logging, logging.handlers
logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)


from ctypes import cdll
libc = cdll.LoadLibrary('libc.so.6')
_setns = libc.setns
CLONE_NEWNET = 0x40000000
#Set default app_manager loop interval =  15 seconds
APP_MANAGER_LOOP_INTERVAL = 15
APP_MANAGER_LOOP_INTERVAL_STDBY = 30
EXIT_FLAG = False

# POSIX signal handler to ensure we shutdown cleanly
def handler(app_manager,signum, frame):
    global EXIT_FLAG

    if not EXIT_FLAG:
        EXIT_FLAG = True
        with open("/misc/app_host/output.txt", "w") as text_file:
            text_file.write("Cleaning up....")
        app_manager.poison_pill = True

        for thread in app_manager.threadList:
            app_manager.syslogger.info("Waiting for %s to finish..." %(thread.name))
            thread.join()
        app_manager.syslogger.info("Cleaning up...")
        return


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

class AppManager(ZtpHelpers):

    def __init__(self,
                 syslog_file=None,
                 syslog_server=None,
                 syslog_port=None,
                 config_file=None):

        super(AppManager, self).__init__(syslog_file=syslog_file,
                                         syslog_server=syslog_server,
                                         syslog_port=syslog_port)
        if config_file is None:
            self.syslogger.info("No Input config provided, bailing out.... Please provide a compatible json input file")
            sys.exit(1)
        else:
            self.config_file = config_file


        # Read the input config.json file for the first time. It will read periodically in the app_manager thread as well.
        try:
            with open(self.config_file, 'r') as json_config_fd:
                self.config = json.load(json_config_fd)
        except Exception as e:
            self.syslogger.info("Failed to load config file. Aborting...")
            sys.exit(1)

        # App manager is just starting, clean out rpfo.state to start afresh

        if "rpfo_state_file" in list(self.config["config"].keys()):
            self.rpfo_file = self.config["config"]["rpfo_state_file"]
        else:
            self.rpfo_file = "/misc/app_host/scratch/rpfo.state"

        try:
            # Remove rpfo.state file
            os.remove(self.rpfo_file)
        except OSError as e:
            self.syslogger.info("Failed to delete rpfo file")
            self.syslogger.info("Removing stale rpfo directory if created")
            try:
                import shutil
                shutil.rmtree(self.rpfo_file, ignore_errors=True)
            except Exception as e:
                self.syslogger.info("Failed to remove stale rpfo directory")


        self.root_lr_user="ztp-user"
        # Check if docker daemon is reachable
        self.check_docker_engine(start_wait_time=60, restart_count=1, terminate_count=15)

        self.standby_rp_present = False
        self.poison_pill = False
        self.threadList = []

        for fn in [self.setup_apps]:
            thread = threading.Thread(target=fn, args=())
            self.threadList.append(thread)
            thread.daemon = True                            # Daemonize thread
            thread.start()                                  # Start the execution



    def check_docker_engine(self,
                            start_wait_time=60,
                            wait_increment=60,
                            restart_count=3,
                            terminate_count=10):
        # Check if docker daemon is reachable. If not wait 2 mins and loop till it is
        docker_engine_up=False
        wait_time=start_wait_time
        start_time=time.time()
        iteration=0
        wait_count=0
        while True:
            iteration+=1
            wait_count+=1
            if iteration == terminate_count:
                self.syslogger.info("Unable to determine docker_engine state, giving up...")
                #self.hostcmd(cmd="service docker stop")
                #self.hostcmd(cmd="service docker start")
                #time.sleep(120)
                #cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker info"
                #docker_engine_status = self.run_bash_timed(cmd, timeout=10)
                #if docker_engine_status["status"]:
                #    self.syslogger.info("Failed to get docker engine state after docker service start. Giving up.." )
                #else:
                #    self.syslogger.info("Docker engine running! Let's proceed...")
                break
            if wait_count > restart_count:
                wait_time=start_wait_time
                wait_count=1
            cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker info"
            docker_engine_status = self.run_bash_timed(cmd, timeout=10)
            if docker_engine_status["status"]:
                self.syslogger.info("Failed to get docker engine state. Output: "+str(docker_engine_status["output"])+", Error: "+str(docker_engine_status["error"]))
                self.syslogger.info("Sleeping for "+str(wait_time)+" seconds before trying again...")
                time.sleep(wait_time)
            else:
                self.syslogger.info("Docker engine running! Let's proceed...")
                docker_engine_up=True
                break
            wait_time=wait_time+wait_increment

        elapsed_time=time.time()-start_time
        if docker_engine_up:
            self.syslogger.info("Time taken for docker engine to be available = "+str(elapsed_time)+"seconds")
        else:
            self.syslogger.info("Docker engine still not up. Elapsed time: "+str(elapsed_time)+"seconds")

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


    def xrCLI(self, cmd):
        cmd = 'export PATH=/pkg/sbin:/pkg/bin:${PATH} && ip netns exec xrnns /pkg/bin/xr_cli -n "%s"' % cmd
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        out, err = process.communicate()
        if process.returncode:
            status = "error"
            output = "Failed to get command output"
        else:
            status = "success"

            output_list = [] 
            output = ""

            for line in out.splitlines():
                fixed_line = line.replace("\n", " ").strip()
                output_list.append(fixed_line)
                if "% Invalid input detected at '^' marker." in fixed_line:
                    status = "error"
                output = filter(None, output_list)  # Removing empty items 
        return {"status": status, "output": output} 

    def admincmd(self, cmd=None):

        if cmd is None:
            return {"status" : "error", "output" : "No command specified"}

        status = "success"


        if self.debug:
            self.logger.debug("Received admin exec command request: \"%s\"" % cmd)

        cmd = "export AAA_USER="+self.root_lr_user+" && source /pkg/bin/ztp_helper.sh && echo -ne \""+cmd+"\\n \" | xrcmd \"admin\""

        self.syslogger.info(cmd)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        out, err = process.communicate()


        if process.returncode:
            status = "error"
            output = "Failed to get command output"
        else:
            output_list = []
            output = ""

            for line in out.splitlines():
                fixed_line= line.replace("\n", " ").strip()
                output_list.append(fixed_line)
                if "syntax error: expecting" in fixed_line:
                    status = "error"
                output = filter(None, output_list)    # Removing empty items

        if self.debug:
            self.logger.debug("Exec command output is %s" % output)

        self.syslogger.info(output)
        return {"status" : status, "output" : output}


    def hostcmd(self, cmd=None):
        if cmd is None:
            return {"status" : "error", "output" : "No command specified"}


        self.syslogger.info("Received host command request: \"%s\"" % cmd)


        result = self.admincmd(cmd="run ssh root@10.0.2.16 "+cmd)

        return {"status" : result["status"], "output" : result["output"]}



    def is_active_rp(self):
        '''method to check if the node executing this daemon is the active RP
        '''
        # Get the current active RP node-name
        exec_cmd = "show redundancy summary"
        show_red_summary = self.xrCLI(exec_cmd)

        if show_red_summary["status"] == "error":
             self.syslogger.info("Failed to get show redundancy summary output from XR")
             return {"status" : "error", "output" : "", "warning" : "Failed to get show redundancy summary output"}

        else:
            try:
                current_active_rp = show_red_summary["output"][2].split()[0]
            except Exception as e:
                self.syslogger.info("Failed to get Active RP from show redundancy summary output")
                return {"status" : "error", "output" : "", "warning" : "Failed to get Active RP, error: " + str(e)}

        cmd = "/sbin/ip netns exec xrnns /pkg/bin/node_list_generation -f MY"

        get_node_name = self.run_bash(cmd)
        my_node_name = ''

        if not get_node_name["status"]:
            my_node_name = get_node_name["output"]
        else:
            self.syslogger.info("Failed to get My Node Name. Output: "+str(get_node_name["output"])+", Error: "+str(get_node_name["output"]))


        if current_active_rp.strip() == my_node_name.strip():
            self.syslogger.info("I am the current RP, take action")
            return {"status" : "success", "output" : True, "warning" : ""}
        else:
            self.syslogger.info("I am not the current RP")
            return {"status" : "success", "output" : False, "warning" : ""}



    def get_peer_rp_ip(self):
        """User defined method in Child Class
           IOS-XR internally uses a private IP address space
           to reference linecards and RPs.

           This method uses XR internal binaries to fetch the
           internal IP address of the Peer RP in an HA setup.
           :param url: Complete url for config to be downloaded
           :param caption: Any reason to be specified when applying
                           config. Will show up in the output of:
                          "show configuration commit list detail"
           :type url: str
           :type caption: str
           :return: Return a dictionary with status and the peer RP IP
                    { 'status': 'error/success',
                      'peer_rp_ip': 'IP address of Peer RP' }
           :rtype: dict
        """
        cmd = "ip netns exec xrnns /pkg/bin/node_list_generation -f MY"
        bash_out = self.run_bash(cmd)
        if not bash_out["status"]:
            my_name = bash_out["output"]
        else:
            self.syslogger.info("Failed to get My Node Name")
            return {"status" : "error", "peer_rp_ip" : ""}

        cmd = "ip netns exec xrnns /pkg/bin/node_conversion -N " + str(my_name)
        bash_out = self.run_bash(cmd)
        if not bash_out["status"]:
            my_node_name = bash_out["output"].replace('\n', '')
        else:
            self.syslogger.info("Failed to convert My Node Name")
            return {"status" : "error", "peer_rp_ip" : ""}


        cmd = "ip netns exec xrnns /pkg/bin/node_list_generation -f ALL"
        bash_out = self.run_bash(cmd)

        if not bash_out["status"]:
            node_name_list = bash_out["output"].split()
        else:
            self.syslogger.info("Failed to get Node Name List")
            return {"status" : "error", "peer_rp_ip" : ""}


        for node in node_name_list:
            if "RP" in node:
                if my_node_name != node:
                    cmd="ip netns exec xrnns /pkg/bin/admin_nodeip_from_nodename -n " + str(node)
                    bash_out = self.run_bash(cmd)

                    if not bash_out["status"]:
                        return {"status" : "success", "peer_rp_ip" : bash_out["output"]}
                    else:
                        self.syslogger.info("Failed to get Peer RP IP")
                        return {"status" : "error", "peer_rp_ip" : ""}

        self.syslogger.info("There is no standby RP!")
        return {"status" : "error", "peer_rp_ip" : ""}



    def scp_to_standby(self, dir_sync=False, src_path=None, dest_path=None, sync_mtu=False):
        """User defined method in Child Class
           Used to scp files from active to standby RP.

           leverages the get_peer_rp_ip() method above.
           Useful to keep active and standby in sync with files
           in the linux environment.
           :param dir_sync: Flag to sync directory using the recursive -r option for scp
           :param src_path: Source directory/file location on Active RP
           :param dest_path: Destination directory/file location on Standby RP
           :param sync_mtu: Flag to enable changing the eth-vf1 MTU for large file syncs 
                            between active and standby RPs
           :type src_path: str
           :type dest_path: str
           :return: Return a dictionary with status based on scp result.
                    { 'status': 'error/success' }
           :rtype: dict
        """

        ethvf1_MTU = 9000
        ethvf1_sync_MTU = 1492

        if any([src_path, dest_path]) is None:
            self.syslogger.info("Incorrect File path\(s\)")
            return {"status" : "error"}

        standby_ip = self.get_peer_rp_ip()

        if standby_ip["status"] == "error":
            return {"status" : "error"}
        else:
            # First collect the mtu of eth-vf1 that connects to the standby RP in xrnns. Scp will likely stall at 2112 Kb because of the high
            # MTU setting on eth-vf1. This is a known issue in Linux kernels with scp for large files. We set the MTU of eth-vf1 to a lower
            # value = 1492 temporarily, initiate the transfer and change back the MTU.
            # See: http://stackoverflow.com/questions/11985008/sending-a-large-file-with-scp-to-a-certain-server-stalls-at-exactly-2112-kb

            # Grab original MTU of eth-vf1 in xrnns:
            # cmd = "ip netns exec xrnns cat /sys/class/net/eth-vf1/mtu"
            # mtu_value = self.run_bash(cmd)
            # self.syslogger.info("Gleaned current MTU of eth-vf1: " + str(mtu_value))

            # if mtu_value["status"]:
            #    self.syslogger.info("Failed to grab MTU of eth-vf1, aborting. Output: "+str(mtu_value["output"])+", Error: "+str(mtu_value["error"]))
            # else:
            #    eth_vf1_mtu = mtu_value["output"]

            self.syslogger.info("Transferring "+str(src_path)+" from Active RP to standby location: " +str(dest_path))

            if sync_mtu:
                eth_vf1_mtu = ethvf1_sync_MTU
            else:
                eth_vf1_mtu = ethvf1_MTU

            self.syslogger.info("Setting eth-vf1 MTU to " +str(eth_vf1_mtu) + " for scp commands")
            if dir_sync:
                self.syslogger.info("Copying entire directory and its subdirectories to standby")
                self.syslogger.info("Force create destination directory, ignore error")
                cmd = "mkdir -p "+str(dest_path)
                standby_bash_cmd = self.execute_cmd_on_standby(cmd = cmd)

                if standby_bash_cmd["status"] == "error":
                    self.syslogger.info("Failed to execute bash cmd: \""+str(cmd)+"\" on the standby RP. Output: "+str(standby_bash_cmd["output"])+". Error: "+str(standby_bash_cmd["error"])+". Ignoring....")
                else:
                    self.syslogger.info("Successfully executed bash cmd: \""+str(cmd)+"\" on the standby RP. Output: "+str(standby_bash_cmd["output"]))

                cmd = "ip netns exec xrnns ifconfig eth-vf1 mtu " + str(eth_vf1_mtu) + " && ip netns exec xrnns scp -o ConnectTimeout=300 -r "+str(src_path)+ "/* root@" + str(standby_ip["peer_rp_ip"]) + ":" + str(dest_path)
            else:
                self.syslogger.info("Copying only the source file to target file location")
                cmd = "ip netns exec xrnns ifconfig eth-vf1 mtu " + str(eth_vf1_mtu) + " && ip netns exec xrnns scp -o ConnectTimeout=300 "+str(src_path)+ " root@" + str(standby_ip["peer_rp_ip"]) + ":" + str(dest_path)
            bash_out = self.run_bash(cmd)

            if bash_out["status"]:
                self.syslogger.info("Failed to transfer file(s) to standby")
                return {"status" : "error"}
            else:
                self.syslogger.info("Reset MTU to original value: " +str(ethvf1_MTU))
                cmd = "ip netns exec xrnns ifconfig eth-vf1 mtu "+str(ethvf1_MTU)
                bash_out = self.run_bash(cmd)

                if bash_out["status"]:
                    self.syslogger.info("Failed to reset MTU on eth-vf1")
                    cmd = "ip netns exec xrnns ifconfig eth-vf1"
                    bash_out = self.run_bash(cmd)
    
                    if bash_out["status"]:
                        self.syslogger.info("Failed to fetch eth-vf1 dump")
                    else:
                        self.syslogger.info(bash_out["output"])
                    return {"status" : "error"}
                else:
                    cmd = "ip netns exec xrnns ifconfig eth-vf1"
                    bash_out = self.run_bash(cmd)

                    if bash_out["status"]:
                        self.syslogger.info("Failed to fetch eth-vf1 dump")
                    else:
                        self.syslogger.info(bash_out["output"])
                    return {"status" : "success"}
                
    def execute_cmd_on_standby(self, cmd=None):
        """User defined method in Child Class
           Used to execute bash commands on the standby RP
           and fetch the output over SSH.
           Leverages get_peer_rp_ip() and run_bash() methods above.
           :param cmd: bash command to execute on Standby RP
           :type cmd: str
           :return: Return a dictionary with status and output
                    { 'status': 'error/success',
                      'output': 'empty/output from bash cmd on standby' }
           :rtype: dict
        """

        if cmd is None:
            self.syslogger.info("No command specified")
            return {"status" : "error", "output" : ""}
        else:
            with tempfile.NamedTemporaryFile(delete=True) as f:
                f.write("#!/bin/bash\n%s" % cmd)
                f.flush()
                f.seek(0,0)
                standby_ip = self.get_peer_rp_ip()
                if standby_ip["status"] == "error":
                    return {"status" : "error", "output" : ""}
                standby_cmd = "ip netns exec xrnns ssh root@"+str(standby_ip["peer_rp_ip"])+ " " + "\"$(< "+str(f.name)+")\""

                bash_out = self.run_bash(standby_cmd)

                if bash_out["status"]:
                    self.syslogger.info("Failed to execute command on standby")
                    return {"status" : "error", "output" : ""}
                else:
                    return {"status" : "success", "output": bash_out["output"]}


    def setup_apps(self):
        '''
           Eventually may support multiple input methods. Currently supports the input
           json file for method_list and parameters.
        '''

        global APP_MANAGER_LOOP_INTERVAL
        global APP_MANAGER_LOOP_INTERVAL_STDBY
       # This method is started as a daemon thread.
       # Keeps running a loop to automatically load an updated json config file if it changes

        while True:
            self.syslogger.info("Back to the top...")
            # Look for a poison pill in case of termination
            if self.poison_pill:
                self.syslogger.info("Received poison pill, terminating app setup thread")
                return

            try:
            # Periodically load up config file to accomodate changes as part of the main thread loop
                with open(self.config_file, 'r') as json_config_fd:
                    self.config = json.load(json_config_fd)
            except Exception as e:
                self.syslogger.info("Failed to load config file. Sleep and retry")
                time.sleep(60)
                continue


            # Only try to bring up apps on an active RP

            check_RP_status =  self.is_active_rp()

            if check_RP_status["status"] == "success":
            # Currently on Standby RP, wait and go back to start of loop
                if not check_RP_status["output"]:
                    self.syslogger.info("Currently running on Standby RP, skipping app bringup. Sleep and Retry")
                    # Create rpfo.state for apps to utilize

                    # Try to read existing rpfo state
                    try:
                        with open(self.rpfo_file, 'r') as rpfo_state_fd:
                            last_rpfo_state = rpfo_state_fd.read()

                        self.syslogger.info("Last rpfo state: "+str(last_rpfo_state))
                        if str(last_rpfo_state) == "active":
                            current_rpfo_state = "standby"
                        elif str(last_rpfo_state) == "standby":
                            current_rpfo_state = "standby"
                        elif str(last_rpfo_state) == "switchover":
                            current_rpfo_state = "standby"
                        else:
                            current_rpfo_state = "standby"
                    except Exception as e:
                        self.syslogger.info("Failed to read last rpfo state. Error: "+str(e))
                        current_rpfo_state = "standby"
                    try:
                        self.syslogger.info("Setting rpfo state to "+str(current_rpfo_state))
                        # Write rpfo state
                        with open(self.rpfo_file, "w") as rpfo_state_fd:
                            rpfo_state_fd.write(current_rpfo_state)
                    except Exception as e:
                        self.syslogger.info("Failed to write rpfo state!")

                    if "app_manager_loop_interval_stdby" in list(self.config["config"].keys()):
                        APP_MANAGER_LOOP_INTERVAL_STDBY = self.config["config"]["app_manager_loop_interval_stdby"]

                    self.syslogger.info("Removing stale running apps.....")

                    try:
                        if "remove_apps_standby" in list(self.config["config"].keys()):
                            remove_apps_standby = self.config["config"]["remove_apps_standby"]
                        else:
                            remove_apps_standby = False

                        self.apps = self.config["config"]["apps"]
                        for app in self.apps:
                            method_obj = getattr(self, str("remove_")+str(app["type"])+"_app")
                            method_out = method_obj(**app)
                            if method_out["status"] == "error":
                                self.syslogger.info("Error executing method " +str(method_obj.__name__)+ " for app with id: "+ str(app["app_id"]) + ", error:" + method_out["output"])
                            else:
                                self.syslogger.info("Result of app manage method: " +str(method_obj.__name__)+" for app with id: "+ str(app["app_id"]) + " is: " + method_out["output"])
                    except Exception as e:
                        self.syslogger.info("Failure while trying to remove apps: " + str(e))

                    self.syslogger.info("Sleeping for seconds: "+str(APP_MANAGER_LOOP_INTERVAL_STDBY))
                    time.sleep(int(APP_MANAGER_LOOP_INTERVAL_STDBY))
                    continue
                else:
                    self.syslogger.info("Currently running on Active RP, register state and launch apps")
                    # Currently on Active RP, determine if standby RP is present, register state. Then launch apps.
                    standby_ip = self.get_peer_rp_ip()

                    if standby_ip["status"] == "error":
                        self.syslogger.info("No standby RP detected or failed to get standby RP xrnns ip")
                        self.standby_rp_present = False
                    else:
                        self.standby_rp_present = True

                    # Try to read existing rpfo state
                    try:
                        with open(self.rpfo_file, 'r') as rpfo_state_fd:
                            last_rpfo_state = rpfo_state_fd.read()

                        self.syslogger.info("Last rpfo state: "+str(last_rpfo_state))
                        if str(last_rpfo_state) == "active":
                            current_rpfo_state = "active"
                        elif str(last_rpfo_state) == "standby":
                            self.syslogger.info("Last rpfo state was standby, switchover occured. Now set it to switchover")
                            current_rpfo_state = "switchover"
                        elif str(last_rpfo_state) == "switchover":
                            # If last rpfo state is switchover, then app_manager will not attempt
                            # to change it. It is upto the app to read, process and then set to
                            # active.
                            self.syslogger.info("RP became active post Switchover")
                            current_rpfo_state = "switchover"
                        else:
                            current_rpfo_state = "active"
                    except Exception as e:
                        self.syslogger.info("Failed to read last rpfo state. Error: "+str(e))
                        current_rpfo_state = "active"


                    try:
                        self.syslogger.info("Setting rpfo state to "+str(current_rpfo_state))
                        # Write rpfo state
                        with open(self.rpfo_file, "w") as rpfo_state_fd:
                            rpfo_state_fd.write(current_rpfo_state)
                    except Exception as e:
                        self.syslogger.info("Failed to write rpfo state!")

                    try:
                        if "app_manager_loop_interval" in list(self.config["config"].keys()):
                            APP_MANAGER_LOOP_INTERVAL = self.config["config"]["app_manager_loop_interval"]

                        self.apps = self.config["config"]["apps"]
                        for app in self.apps:
                            method_obj = getattr(self, str("manage_")+str(app["type"])+"_app")
                            method_out = method_obj(**app)
                            if method_out["status"] == "error":
                                self.syslogger.info("Error executing method " +str(method_obj.__name__)+ " for app with id: "+ str(app["app_id"]) + ", error:" + method_out["output"])
                            else:
                                self.syslogger.info("Result of app manage method: " +str(method_obj.__name__)+" for app with id: "+ str(app["app_id"]) + " is: " + method_out["output"])
                    except Exception as e:
                        self.syslogger.info("Failure while setting up apps: " + str(e))

            elif check_RP_status["status"] == "error":
                self.syslogger.info("Failed to fetch RP state, try again in next iteration")
            time.sleep(int(APP_MANAGER_LOOP_INTERVAL))


    def check_docker_running(self, docker_name):
        '''Internal helper method to check if a docker with name docker_name is running
        '''

        cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker ps -f name="+str(docker_name)

        docker_status = self.run_bash_timed(cmd, timeout=10)
        if docker_status["status"]:
            self.syslogger.info("Failed to get docker state. Output: "+str(docker_status["output"])+", Error: "+str(docker_status["error"]))
        else:
            docker_state = docker_status["output"]

        output_list = []
        output = ''

        for line in docker_status["output"].splitlines():
            fixed_line= line.replace("\n", " ").strip()
            output_list.append(fixed_line)
            output = filter(None, output_list)    # Removing empty items

        for line in output:
            if line.split()[-1] == docker_name:
                self.syslogger.info("Docker container " +str(docker_name)+ " is running")
                return {"status" : True}

        return {"status" : False}


    def docker_image_present(self, image_tag=None):

        if image_tag is None:
            return{"status": "error",
                   "output": "No image tag provided, cannot check if docker image is present on current RP"}
        else:
            # Check that the expected docker image is available in local registry
            cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker inspect --type=image " + str(image_tag) + " 2> /dev/null"
            docker_inspect = self.run_bash_timed(cmd, timeout=10)

            if docker_inspect["status"]:
                self.syslogger.info("Failed to inspect docker image. Output: "+str(docker_inspect["output"])+", Error: "+str(docker_inspect["output"]))
                return {"status" : "error", "output" : "Failed to inspect docker image"}
            else:
                self.syslogger.info("Docker inspect command successful")
                if image_tag in str(json.loads(docker_inspect["output"])[0]["RepoTags"]):
                    self.syslogger.info("Docker image with name: "+str(image_tag)+" now available")
                    return {"status" : "success", "output" : "Docker image with tag: "+str(image_tag)+" is present locally on RP"}


    def update_docker_config(self,
                             app_id=None,
                             key=None,
                             value=None):
        try:
            app_index=0
            for app in self.config["config"]["apps"]:
                if app["app_id"] == app_id:
                    self.config["config"]["apps"][app_index][key] = value
                    break
                app_index=app_index+1

            try:
                # Write updated config to input json file. This will set it up for switchover scenarios
                with open(self.config_file, "w") as input_config_fd:
                    input_config_fd.write(json.dumps(self.config, indent=4))
                return {"status" : "success", "output" : "Successfully updated config for app with app_id: "+str(app_id)}
            except Exception as e:
                self.syslogger.info("Failed to write updated config to config file")
                raise Exception("Failed to write updated config to config file")
        except Exception as e:
            self.syslogger.info("Updated key= "+str(key)+" with value=" +str(value)+ " for app with app_id="+str(app_id))
            return {"status" : "error", "output" : "Unable to update config for app with app_id: "+str(app_id)}

    def setup_json_standby(self):
        # Set up a json file with pointers to local file-based artifacts on current standby during
        # app_setup on active RP

        # Since the input json config file on active RP is updated during setup, just copy over the
        # current updated file to an equivalent location on standby RP.

        # Determine the absolute path of the current config file

        config_file_path = os.path.abspath(self.config_file)
        scp_output = self.scp_to_standby(src_path=config_file_path,
                                         dest_path=config_file_path)

        if scp_output["status"] == "error":
            self.syslogger.info("Failed to set up json config file on Standby RP")
            return {"status" : "error"}
        else:
            self.syslogger.info("Successfully set up json config file on standby RP")
            return {"status" : "success"}


    def remove_docker_app(self,
                          type="docker",
                          app_id=None,
                          docker_scratch_folder='/tmp',
                          docker_container_name=None,
                          docker_image_name=None,
                          docker_registry=None,
                          docker_image_url=None,
                          docker_image_filepath=None,
                          docker_image_action="import",
                          docker_mount_volumes=None,
                          docker_cmd=None,
                          docker_run_misc_options=None,
                          sync_to_standby=False,
                          reload_capable=False):

        # Check that the docker daemon is reachable before trying anything
        self.check_docker_engine(start_wait_time=60, restart_count=1, terminate_count=15)
        if docker_container_name is None:
            self.syslogger.info("Docker container name not specified")
            return {"status" : "error", "output" : "Docker container name not specified"}

        if self.check_docker_running(docker_container_name)["status"]:
            self.syslogger.info("Removing app")
            try:
                cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker rm -f "+str(docker_container_name)+ " > /dev/null 2>&1"
                docker_rm = self.run_bash(cmd)
                if docker_rm["status"]:
                    self.syslogger.info("Failed to run docker rm -f command on container app, container might not exist - Ignoring.... Output: "+str(docker_rm["output"])+", Error: "+str(docker_rm["error"]))
            except Exception as e:
                self.syslogger.info("Failed to remove app. Error is: " +str(e))
                return {"status" : "error", "output" : "Failed to remove container"}
            return {"status" : "success", "output" : "Docker container successfully cleaned up"}
        else:
            self.syslogger.info("Docker app not running. Nothing to remove.")
            return {"status" : "success",  "output" : "Docker app not running. Nothing to remove"}



    def manage_docker_app(self,
                          type="docker",
                          app_id=None,
                          docker_scratch_folder='/tmp',
                          docker_container_name=None,
                          docker_image_name=None,
                          docker_registry=None,
                          docker_image_url=None,
                          docker_image_filepath=None,
                          docker_image_action="import",
                          docker_mount_volumes=None,
                          docker_cmd=None,
                          docker_run_misc_options=None,
                          sync_to_standby=False,
                          reload_capable=False):


        if sync_to_standby:
            self.syslogger.info("Sync to Standby for docker images is Set")
        # Check that the docker daemon is reachable before trying anything
        self.check_docker_engine(terminate_count=2)

        if docker_image_name is None:
            self.syslogger.info("Docker image location not specified")
            return {"status" : "error", "output" : "Docker image location not specified"}

        if docker_container_name is None:
            self.syslogger.info("Docker container name not specified")
            return {"status" : "error", "output" : "Docker container name not specified"}

        if docker_registry is None:
            # No docker registry specified, check for url to download docker image
            if docker_image_url is None:
                if docker_image_filepath is None:
                    self.syslogger.info("No Docker registry, image url or image file path specified")
                    return {"status" : "error", "output" : "Docker image path,url or registry not provided"}

        # Config files may change during operation, periodically sync config_mount volume to standby
        # during each iteration of the thread

        if self.standby_rp_present:
            if docker_mount_volumes is not None:
                try:
                    for mount_map in docker_mount_volumes:
                        if "config_mount" in list(mount_map.keys()):
                            config_mount_sync = self.scp_to_standby(dir_sync=True,
                                                                    src_path=mount_map["config_mount"]["host"],
                                                                    dest_path=mount_map["config_mount"]["host"])
                            if config_mount_sync["status"] == "error":
                                self.syslogger.info("Failed to sync config mount to standby RP")
                                return {"status" : "error", "output" : "Failed to sync config mount for docker container."}
                            else:
                                self.syslogger.info("Successfully synced config mount to standby RP")
                except Exception as e:
                    self.syslogger.info("Exception while syncing config mount to standby RP. Error is: "+str(e))
                    return {"status" : "error", "output" : "Exception while syncing config mount to standby RP"}


        if self.check_docker_running(docker_container_name)["status"]:
            self.syslogger.info("Skip app bringup, app already running")
            return {"status" : "success", "output" : "Docker container already running"}
        else:
            # We don't know why the container is not running or why it died,  so remove before trying to launch again 
            try:
                cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker rm -f "+str(docker_container_name)+ " > /dev/null 2>&1"
                docker_rm = self.run_bash(cmd)
                if docker_rm["status"]:
                    self.syslogger.info("Failed to run docker rm -f command on dormant container, container might not exist - Ignoring.... Output: "+str(docker_rm["output"])+", Error: "+str(docker_rm["error"]))
            except Exception as e:
                self.syslogger.info("Failed to remove dormant container with same name. Error is: " +str(e))
                return {"status" : "error", "output" : "Failed to remove dormant container with same name"}

            image_setup = self.fetch_docker_image(app_id,
                                                  docker_scratch_folder,
                                                  docker_image_name,
                                                  docker_registry,
                                                  docker_image_url,
                                                  docker_image_filepath,
                                                  docker_image_action,
                                                  sync_to_standby)
            if image_setup["status"] == "error":
                self.syslogger.info("Failed to set up docker image. Error is " +str(image_setup["output"]))
                return {"status" : "error", "output" : "Failed to set up docker image with tag: "+str(docker_image_name)}
            else:
                self.syslogger.info("Docker image set up successfully, proceeding with docker bring-up")

                container_setup =  self.launch_docker_container(docker_image_name,
                                                                docker_container_name,
                                                                docker_mount_volumes,
                                                                docker_cmd,
                                                                docker_run_misc_options)
                if container_setup["status"] == "error":
                    self.syslogger.info("Failed to launch the docker app")
                else:
                    self.syslogger.info("Docker app successfully launched")
                    # Check if the sync_to_standby flag is set
                    if sync_to_standby and self.standby_rp_present:
                        # Set up the current (updated) json config file for the app_manager running on standby
                        json_file_standby = self.setup_json_standby()
                        if json_file_standby["status"] == "success":
                            self.syslogger.info("Synced json input file to standby")
                            return {"status" : "success", "output": "Application successfully launched on Active RP and required artifacts set up on standby RP"}
                        else:
                            self.syslogger.info("Failed to sync json input file to standby")
                    else:
                        return {"status" : "success", "output": "Application successfully launched on Active RP"}


    def fetch_docker_image(self,
                           app_id=None,
                           docker_scratch_folder="/tmp",
                           docker_image_name=None,
                           docker_registry=None,
                           docker_image_url=None,
                           docker_image_filepath=None,
                           docker_image_action="import",
                           sync_to_standby=False):

        # Current RP could be active RP during initial deplopyment (registry, url, filepath all OK) or
        # a standby RP that just become active (filepath only option as set up by THEN active RP).
        # Start with filepath first, only then fall to url, then registry.

        # Owing to the small size of the /misc/app_host volume that is used for docker on XR,
        # Clean up existing image with existing name. We always try to load/import image since
        # an updated image may have become available.

        try:
            cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker rmi "+str(docker_image_name)+" > /dev/null 2>&1"
            rm_image=self.run_bash(cmd)
            if rm_image["status"]:
                self.syslogger.info("Failed to run docker rmi on existing docker image with name: "+str(docker_image_name)+", but continuing.Output: "+str(rm_image["output"])+" Error: "+str(rm_image["error"]))
            else:
                self.syslogger.info("Removed existing docker image with name: "+str(docker_image_name))
        except Exception as e:
            self.syslogger.info("Failed to remove existing docker image with name: "+str(docker_image_name)) 

        # Copy docker image tarball to scratch folder and load/import it
        try:
            # Start by checking if image filepath is specified
            if docker_image_filepath is not None:
                if self.valid_path(docker_image_filepath):
                    # Move the file to scratch folder
                    try:
                        import shutil
                        filename = posixpath.basename(docker_image_filepath)
                        shutil.move(docker_image_filepath, os.path.join(docker_scratch_folder, filename))
                        folder = docker_scratch_folder
                        filepath = os.path.join(folder, filename)

                        # Update the filepath to reflect the scratch folder location
                        update_app = self.update_docker_config(app_id, key="docker_image_filepath", value=filepath)

                        if update_app["status"] == "error":
                            self.syslogger.info("App_id: "+str(app_id)+", Failed to update app configuration, aborting...")
                            return {"status": "error",  "output" : "App_id: "+str(app_id)+", Failed to update app configuration, aborting..."}
                        else:
                            self.syslogger.info("App_id: "+str(app_id)+", Successfully updated app configuration ")
                    except Exception as e:
                        self.syslogger.info("Failed to copy image to the scratch folder. Error is "+str(e))
                        return {"status": "error",  "output" : "Failed to copy and load docker tarball, bailing out"}
                else:
                    self.syslogger.info("Docker tarball filepath not valid, Trying the docker_image_url if present")
                    #return {"status": "error",  "output" : "Unable to copy and load docker tarball, invalid path."}
                    if docker_image_url is not None:
                        docker_download = self.download_file(docker_image_url, destination_folder=docker_scratch_folder)

                        if docker_download["status"] == "error":
                            self.syslogger.info("Failed to download docker container tar ball")
                            return {"status" : "error", "output" : "Failed to download docker tar ball from url"}
                        else:
                            filename = docker_download["filename"]
                            folder = docker_download["folder"]
                            filepath = os.path.join(folder, filename)

                            # Update the filepath to reflect the scratch folder location
                            update_app = self.update_docker_config(app_id, key="docker_image_filepath", value=filepath)

                            if update_app["status"] == "error":
                                self.syslogger.info("App_id: "+str(app_id)+"Failed to update app configuration, aborting...")
                                return {"status": "error",  "output" : "App_id: "+str(app_id)+"Failed to update app configuration, aborting..."}
                            else:
                                self.syslogger.info("App_id: "+str(app_id)+"Successfully updated app configuration ")

            elif docker_image_url is not None:
                docker_download = self.download_file(docker_image_url, destination_folder=docker_scratch_folder)

                if docker_download["status"] == "error":
                    self.syslogger.info("Failed to download docker container tar ball")
                    return {"status" : "error", "output" : "Failed to download docker tar ball from url"}
                else:
                    filename = docker_download["filename"]
                    folder = docker_download["folder"]
                    filepath = os.path.join(folder, filename)

                    # Update the filepath to reflect the scratch folder location
                    update_app = self.update_docker_config(app_id, key="docker_image_filepath", value=filepath)

                    if update_app["status"] == "error":
                        self.syslogger.info("App_id: "+str(app_id)+"Failed to update app configuration, aborting...")
                        return {"status": "error",  "output" : "App_id: "+str(app_id)+"Failed to update app configuration, aborting..."}
                    else:
                        self.syslogger.info("App_id: "+str(app_id)+"Successfully updated app configuration ")
            elif docker_registry is not None:
                # docker_registry is expected to be a dictionary specifying:
                #   1.  Type of registry: insecure, self-signed, dockerhub
                #   2.  Download URLs for
                #          [ '/etc/sysconfig/docker for insecure registry' ,
                #            '<common-name-CA>:<port> file for self-signed registry containing the cert']

                self.syslogger.info("Docker registry not supported yet")
                return {"status" : "error", "output" : "Docker registry not supported yet"}

            # Load/import the docker tarball based on specified action

            if docker_image_action == "import":
                cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker import " +str(filepath)+ "  " + str(docker_image_name)
                docker_image_op = self.run_bash(cmd, timeout=10)

                if docker_image_op["status"]:
                    self.syslogger.info("Failed to import docker image. Output: "+str(docker_image_op["output"])+", Error: "+str(docker_image_op["error"]))
                    return {"status" : "error", "output" : "Failed to import docker image"}
                else:
                    self.syslogger.info("Docker image import command ran successfully")
            elif docker_image_action == "load":
                cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker load --input " +str(filepath)
                docker_image_op = self.run_bash(cmd)

                if docker_image_op["status"]:
                    self.syslogger.info("Failed to load docker tarball. Output: "+str(docker_image_op["output"])+", Error: "+str(docker_image_op["error"]))
                    return {"status" : "error", "output" : "Failed to load docker tarball"}
                else:
                    self.syslogger.info("Docker tarball loaded successfully")


            check_image = self.docker_image_present(docker_image_name)
            if check_image["status"] == "error":
                self.syslogger.info("Docker image not available, some error occured. Will retry in next iteration")
                return {"status" : "error", "output" : "Docker image not available. Will retry in next iteration"}
            else:
                self.syslogger.info("Docker image is now available on current Active RP")

                # If sync_to_standby is set, sync docker image to standby
                if sync_to_standby and self.standby_rp_present :
                    # Copy the image tarball from the scratch folder to the same location on standby RP
                    docker_image_sync_standby = self.scp_to_standby(src_path=filepath,
                                                                    dest_path=filepath,
                                                                    sync_mtu=True)
                    if docker_image_sync_standby["status"] == "error":
                        self.syslogger.info("Failed to set up json config file on Standby RP")
                        return {"status" : "error"}
                    else:
                        self.syslogger.info("Successfully set up json config file on standby RP")
                        return {"status" : "success"}
                else:
                    self.syslogger.info("sync_to_standby is off, not syncing docker image tar ball to standby RP")
                    return {"status" : "success"}

        except Exception as e:
            self.syslogger.info("Failed to load/import Docker image. Error is "+str(e))
            return {"status" : "error", "output" : "Failed to load/import Docker image"}


    def launch_docker_container(self,
                                docker_image_name=None,
                                docker_container_name=None,
                                docker_mount_volumes=None,
                                docker_cmd=None,
                                docker_run_misc_options=None):
        # We don't know why the container died, so remove properly before continuing
        #try:
        #    cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker rm -f "+str(docker_container_name)+ " > /dev/null 2>&1"
        #    docker_rm = self.run_bash(cmd)
        #    if docker_rm["status"]:
        #        self.syslogger.info("Failed to run docker rm -f command on dormant container, container might not exist - Ignoring.... Output: "+str(docker_rm["output"])+", Error: "+str(docker_rm["error"]))
        #except Exception as e:
        #    self.syslogger.info("Failed to remove dormant container with same name. Error is: " +str(e))
        #    return {"status" : "error", "output" : "Failed to remove dormant container with same name"}

        #Clean up any dangling images in case image was already present
        cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker rmi $(docker images --quiet --filter \"dangling=true\") > /dev/null 2>&1"
        rm_dangling_images=self.run_bash(cmd)
        if rm_dangling_images["status"]:
            self.syslogger.info("Failed to remove dangling docker images, but continuing.Output: "+str(rm_dangling_images["output"])+" Error: "+str(rm_dangling_images["error"]))
        else:
            self.syslogger.info("Removed dangling docker images")

        # Set up Docker mount volumes if specified

        try:
            docker_mount_options = ""
            if docker_mount_volumes is not None:
                for mount_map in docker_mount_volumes:
                    if "netns_mount" in list(mount_map.keys()):
                        mount_cmd = " -v "+str(mount_map["netns_mount"]["host"])+":"+str(mount_map["netns_mount"]["container"])+" "
                        docker_mount_options += str(mount_cmd)
                    if "config_mount" in list(mount_map.keys()):
                        mount_cmd = " -v "+str(mount_map["config_mount"]["host"])+":"+str(mount_map["config_mount"]["container"])+" "
                        docker_mount_options += str(mount_cmd)
                    if "misc_mounts" in list(mount_map.keys()):
                        for mount in mount_map["misc_mounts"]:
                            if mount["host"] != "" and mount["container"] != "":
                                mount_host = mount["host"]
                                mount_container = mount["container"]
                                mount_cmd = " -v "+str(mount_host)+":"+str(mount_container)+" "
                                docker_mount_options += str(mount_cmd)
        except Exception as e:
            self.syslogger.info("Failed to determine mount for the docker container. Error is: "+str(e))
            return {"status" : "error", "output" : "Failed to determine mount for the docker container"}

        # Spin up the container
        try:
            cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker run "+ str(docker_mount_options)+" "+ str(docker_run_misc_options)+ " --name " +str(docker_container_name) + " " + str(docker_image_name) + " " + str(docker_cmd)
            self.syslogger.info("Docker Launch command: "+str(cmd))
            docker_launch = self.run_bash(cmd)

            if docker_launch["status"]:
                self.syslogger.info("Failed to spin up the docker container. Output: "+str(docker_launch["output"])+", Error: "+str(docker_launch["error"]))
                return {"status" : "error", "output" : "Failed to spin up the docker container"}
            else:
                if self.check_docker_running(docker_container_name)["status"]:
                    self.syslogger.info("Docker container is now up and running!")
                    return {"status" : "success", "output" : "Docker container is now up and running!"}
                else:
                    self.syslogger.info("Docker container failed to launch!")
                    return {"status" : "error", "output" : "Docker container failed to launch!"}
        except Exception as e:
            self.syslogger.info("Failed to spin up docker app. Error is "+str(e))
            return {"status" : "error", "output" : "Failed to spin up docker app!"}


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--json-config', action='store', dest='json_config',
                    help='Specify the JSON file describing list of apps and associated metadata')
    parser.add_argument('-v', '--verbose', action='store_true',
                    help='Enable verbose logging')


    results = parser.parse_args()
    if results.verbose:
        logger.info("Starting verbose debugging")
        logging.basicConfig()
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)


    if results.json_config is None:
        logger.info("No json config provided, aborting....")
        sys.exit(1)
    else:
        app_manager = AppManager(syslog_file="/var/log/app_manager",
                                 config_file=results.json_config)

    # Register our handler for keyboard interrupt and termination signals
    signal.signal(signal.SIGINT, partial(handler, app_manager))
    signal.signal(signal.SIGTERM, partial(handler, app_manager))

    # The process main thread does nothing but wait for signals
    signal.pause()

    sys.exit(0)
