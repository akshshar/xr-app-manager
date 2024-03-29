#!/usr/bin/env python

import sys
sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers
import pdb
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


class Xr7lSystemHelper(ZtpHelpers):

    def __init__(self,
                 syslog_file=None,
                 syslog_server=None,
                 syslog_port=None):

        super(Xr7lSystemHelper, self).__init__(syslog_file=syslog_file,
                                             syslog_server=syslog_server,
                                             syslog_port=syslog_port)

        self.root_lr_user = "ztp-user"
        standby_status = self.is_ha_setup()
        if standby_status["status"] == "success":
            if not standby_status["output"]:
                self.syslogger.info("Standby RP not present")
                self.ha_setup = False
            else:
                self.syslogger.info("Standby RP is present")
                self.ha_setup = True
        else:
                self.syslogger.info("Failed to get standby status, bailing out")
                self.exit = True


        # Am I the active RP?
        check_active_rp = self.is_active_rp()

        if check_active_rp["status"] == "success":
            if check_active_rp["output"]:
                self.active_rp = True
                self.syslogger.info("Running on active RP")
            else:
                self.active_rp = False
                self.syslogger.info("Not running on active RP")
        else:
            self.syslogger.info("Failed to check current RP node's state")
            self.exit =  True


        self_ip = self.get_rp_ip()
        if self_ip["status"] == "error":
            self.syslogger.info("Failed to fetch active RP IP, exiting")
            self.exit = True
        else:
            self.active_rp_ip = self_ip["rp_ip"]

        standby_ip = self.get_peer_rp_ip()
        if standby_ip["status"] == "error":
            self.syslogger.info("Failed to fetch peer RP IP, exiting")
            self.exit = True
        else:
            self.standby_rp_ip = standby_ip["peer_rp_ip"]

        self.exit = False



    def valid_path(self, file_path):
        return os.path.isfile(file_path)

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


    def is_active_rp(self):
        '''method to check if the node executing this daemon is the active RP
        '''
        # Get the current active RP node-name
        exec_cmd = "show redundancy summary"
        show_red_summary = self.xrcmd({"exec_cmd" : exec_cmd})

        if show_red_summary["status"] == "error":
             self.syslogger.info("Failed to get show redundancy summary output from XR")
             return {"status" : "error", "output" : "", "warning" : "Failed to get show redundancy summary output"}

        else:
            try:
                current_active_rp = show_red_summary["output"][2].split()[0]
            except Exception as e:
                self.syslogger.info("Failed to get Active RP from show redundancy summary output")
                return {"status" : "error", "output" : "", "warning" : "Failed to get Active RP, error: " + str(e)}

        cmd = "source /pkg/etc/xr_startup_envs.sh && /sbin/ip netns exec xrnns /pkg/bin/node_list_generation -f MY"

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
        cmd = "source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/node_list_generation -f MY"
        bash_out = self.run_bash(cmd)
        if not bash_out["status"]:
            my_name = bash_out["output"]
        else:
            self.syslogger.info("Failed to get My Node Name")
            return {"status" : "error", "peer_rp_ip" : ""}

        cmd = "source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/node_conversion -N " + str(my_name)
        bash_out = self.run_bash(cmd)
        if not bash_out["status"]:
            my_node_name = bash_out["output"].replace('\n', '')
        else:
            self.syslogger.info("Failed to convert My Node Name")
            return {"status" : "error", "peer_rp_ip" : ""}


        cmd = "source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/node_list_generation -f ALL"
        bash_out = self.run_bash(cmd)

        if not bash_out["status"]:
            node_name_list = bash_out["output"].split()
        else:
            self.syslogger.info("Failed to get Node Name List")
            return {"status" : "error", "peer_rp_ip" : ""}


        for node in node_name_list:
            if node.startswith("node"):
                node_name = node[len("node"):]
            else:
                node_name = node

            if "RP" in node:
                if my_node_name != node:
                    cmd="source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n " + str(node_name.replace("_", "/")+" 2>&1")
                    bash_out = self.run_bash(cmd)

                    if not bash_out["status"]:
                        return {"status" : "success", "peer_rp_ip" : bash_out["output"]}
                    else:
                        self.syslogger.info("Failed to get Peer RP IP")
                        return {"status" : "error", "peer_rp_ip" : ""}

        self.syslogger.info("There is no standby RP!")
        return {"status" : "error", "peer_rp_ip" : ""}


    def get_rp_ip(self):
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
        cmd = "source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/node_list_generation -f MY"
        bash_out = self.run_bash(cmd)
        if not bash_out["status"]:
            my_node_name = bash_out["output"]
            if "RP" in my_node_name:
                cmd="source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n " + str(my_node_name.strip()+" 2>&1")
                print(cmd)
                bash_out = self.run_bash(cmd)

                if not bash_out["status"]:
                    return {"status" : "success", "rp_ip" : bash_out["output"]}
                else:
                    self.syslogger.info("Failed to get RP IP")
                    return {"status" : "error", "rp_ip" : ""}
        else:
            self.syslogger.info("Failed to get My Node Name")
            return {"status" : "error", "rp_ip" : ""}




    def is_ha_setup(self):

        try:
            # Get the current active RP node-name
            exec_cmd = "show redundancy summary"
            show_red_summary = self.xrcmd({"exec_cmd" : exec_cmd})

            if show_red_summary["status"] == "error":
                self.syslogger.info("Failed to get show redundancy summary output from XR")
                return {"status" : "error", "output" : "", "warning" : "Failed to get show redundancy summary output"}
            else:
                try:
                    if "N/A" in show_red_summary["output"][2].split()[1]:
                        return {"status" : "success", "output": False} 
                    else:
                        return {"status" : "success", "output": True} 
                except Exception as e:
                    self.syslogger.info("Failed to extract standby status from show redundancy summary output")
                    return {"status" : "error", "output" : "Failed to get Active RP, error: " + str(e)}
        except Exception as e:
            self.syslogger.info("Failed to extract standby status from show redundancy summary output")
            return {"status" : "error", "output" : "Failed to get Active RP, error: " + str(e)}





    def scp_to_standby(self, dir_sync=False, src_path=None, dest_path=None, sync_mtu=False):
        """User defined method in Child Class
           Used to scp files from active to standby RP.
           leverages the get_peer_rp_ip() method above.
           Useful to keep active and standby in sync with files
           in the linux environment.
           :param dir_sync: Flag to sync directory using the recursive -r option for scp
           :param src_path: Source directory/file location on Active RP
           :param dest_path: Destination directory/file location on Standby RP
           :param sync_mtu: Flag to enable changing the eth-vf1.3074 MTU for large file syncs 
                            between active and standby RPs
           :type src_path: str
           :type dest_path: str
           :return: Return a dictionary with status based on scp result.
                    { 'status': 'error/success' }
           :rtype: dict
        """

        ethvf1_MTU = 9400
        ethvf1_sync_MTU = 1500

        if any([src_path, dest_path]) is None:
            self.syslogger.info("Incorrect File path\(s\)")
            return {"status" : "error"}
 
        standby_ip = self.standby_rp_ip
        active_ip = self.active_rp_ip

        if standby_ip is "":
            return {"status" : "error"}
        else:
            # First collect the mtu of eth-vf1.3074 that connects to the standby RP in xrnns. Scp will likely stall at 2112 Kb because of the high
            # MTU setting on eth-vf1.3074. This is a known issue in Linux kernels with scp for large files. We set the MTU on eth-vf1.3074 to a lower
            # value = 1492 temporarily, initiate the transfer and change back the MTU.
            # See: http://stackoverflow.com/questions/11985008/sending-a-large-file-with-scp-to-a-certain-server-stalls-at-exactly-2112-kb

            # Grab original MTU of eth-vf1.3074 in xrnns:
            # cmd = "ip netns exec xrnns cat /sys/class/net/eth-vf1.3074/mtu"
            # mtu_value = self.run_bash(cmd)
            # self.syslogger.info("Gleaned current MTU of eth-vf1.3074: " + str(mtu_value))

            # if mtu_value["status"]:
            #    self.syslogger.info("Failed to grab MTU of eth-vf1.3074, aborting. Output: "+str(mtu_value["output"])+", Error: "+str(mtu_value["error"]))
            # else:
            #    eth_vf1_mtu = mtu_value["output"]

            self.syslogger.info("Transferring "+str(src_path)+" from Active RP to standby location: " +str(dest_path))

            if sync_mtu:
                eth_vf1_mtu = ethvf1_sync_MTU
            else:
                eth_vf1_mtu = ethvf1_MTU

            self.syslogger.info("Setting eth-vf1.3074 MTU to " +str(eth_vf1_mtu) + " for scp commands")
            if dir_sync:
                self.syslogger.info("Copying entire directory and its subdirectories to standby")
                self.syslogger.info("Force create destination directory, ignore error")
                cmd = "mkdir -p "+str(dest_path)
                standby_bash_cmd = self.execute_cmd_on_standby(cmd = cmd)

                if standby_bash_cmd["status"] == "error":
                    self.syslogger.info("Failed to execute bash cmd: \""+str(cmd)+"\" on the standby RP. Output: "+str(standby_bash_cmd["output"])+". Error: "+str(standby_bash_cmd["error"])+". Ignoring....")
                else:
                    self.syslogger.info("Successfully executed bash cmd: \""+str(cmd)+"\" on the standby RP. Output: "+str(standby_bash_cmd["output"]))

                cmd = "ip netns exec xrnns ifconfig eth-vf1.3074 mtu " + str(eth_vf1_mtu) + " && ip netns exec xrnns scp -o StrictHostKeyChecking=no -o ConnectTimeout=300 -r "+str(src_path)+ "/* root@" + str(standby_ip) + ":" + str(dest_path)
            else:
                self.syslogger.info("Copying only the source file to target file location")
                cmd = "ip netns exec xrnns ifconfig eth-vf1.3074 mtu " + str(eth_vf1_mtu) + " && ip netns exec xrnns scp -o StrictHostKeyChecking=no -o ConnectTimeout=300 "+str(src_path)+ " root@" + str(standby_ip) + ":" + str(dest_path)
            bash_out = self.run_bash(cmd)

            if bash_out["status"]:
                self.syslogger.info("Failed to transfer file(s) to standby")
                return {"status" : "error"}
            else:
                self.syslogger.info("Reset MTU to original value: " +str(ethvf1_MTU))
                cmd = "ip netns exec xrnns ifconfig eth-vf1.3074 mtu "+str(ethvf1_MTU)
                bash_out = self.run_bash(cmd)

                if bash_out["status"]:
                    self.syslogger.info("Failed to reset MTU on eth-vf1.3074")
                    cmd = "ip netns exec xrnns ifconfig eth-vf1.3074"
                    bash_out = self.run_bash(cmd)
    
                    if bash_out["status"]:
                        self.syslogger.info("Failed to fetch eth-vf1.3074 dump")
                    else:
                        self.syslogger.info(bash_out["output"])
                    return {"status" : "error"}
                else:
                    cmd = "ip netns exec xrnns ifconfig eth-vf1.3074"
                    bash_out = self.run_bash(cmd)

                    if bash_out["status"]:
                        self.syslogger.info("Failed to fetch eth-vf1.3074 dump")
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
            with tempfile.NamedTemporaryFile(delete=False) as f:
                f.write("#!/bin/bash\n%s" % cmd)
                f.flush()
                f.seek(0,0)

                standby_ip = self.standby_rp_ip
                if standby_ip is "":
                    return {"status" : "error", "output" : "", "error" : "Failed to get standby RP ip. No Standby?"}
                standby_cmd = "ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@"+str(standby_ip)+ " " + "\"$(< "+str(f.name)+")\""

                self.syslogger.info("Standby cmd: "+str(standby_cmd))

                bash_out = self.run_bash(standby_cmd)

                if bash_out["status"]:
                    self.syslogger.info("Failed to execute command on standby")
                    return {"status" : "error", "output" : "", "error": bash_out["error"]}
                else:
                    return {"status" : "success", "output": bash_out["output"], "error": ""}




    def scp_from_standby(self, dir_sync=False, src_path=None, dest_path=None, sync_mtu=False):
        """User defined method in Child Class
           Used to scp files from active to standby RP.
           leverages the get_peer_rp_ip() method above.
           Useful to keep active and standby in sync with files
           in the linux environment.
           :param dir_sync: Flag to sync directory using the recursive -r option for scp
           :param src_path: Source directory/file location on Active RP
           :param dest_path: Destination directory/file location on Standby RP
           :param sync_mtu: Flag to enable changing the eth-vf1.3074 MTU for large file syncs 
                            between active and standby RPs
           :type src_path: str
           :type dest_path: str
           :return: Return a dictionary with status based on scp result.
                    { 'status': 'error/success' }
           :rtype: dict
        """

        ethvf1_MTU = 9400
        ethvf1_sync_MTU = 1500

        if any([src_path, dest_path]) is None:
            self.syslogger.info("Incorrect File path\(s\)")
            return {"status" : "error"}

        standby_ip = self.standby_rp_ip
        active_ip = self.active_rp_ip

        if standby_ip is "":
            return {"status" : "error"}
        else:
            # First collect the mtu of eth-vf1.3074 that connects to the standby RP in xrnns. Scp will likely stall at 2112 Kb because of the high
            # MTU setting on eth-vf1.3074. This is a known issue in Linux kernels with scp for large files. We set the MTU on eth-vf1.3074 to a lower
            # value = 1492 temporarily, initiate the transfer and change back the MTU.
            # See: http://stackoverflow.com/questions/11985008/sending-a-large-file-with-scp-to-a-certain-server-stalls-at-exactly-2112-kb

            # Grab original MTU of eth-vf1.3074 in xrnns:
            # cmd = "ip netns exec xrnns cat /sys/class/net/eth-vf1.3074/mtu"
            # mtu_value = self.run_bash(cmd)
            # self.syslogger.info("Gleaned current MTU of eth-vf1.3074: " + str(mtu_value))

            # if mtu_value["status"]:
            #    self.syslogger.info("Failed to grab MTU of eth-vf1.3074, aborting. Output: "+str(mtu_value["output"])+", Error: "+str(mtu_value["error"]))
            # else:
            #    eth_vf1_mtu = mtu_value["output"]

            self.syslogger.info("Transferring "+str(src_path)+" from Standby RP to Active RP location: " +str(dest_path))

            if sync_mtu:
                eth_vf1_mtu = ethvf1_sync_MTU
            else:
                eth_vf1_mtu = ethvf1_MTU

            self.syslogger.info("Setting eth-vf1.3074 MTU on Standby to " +str(eth_vf1_mtu) + " for scp commands")
            if dir_sync:
                self.syslogger.info("Copying entire directory and its subdirectories to Active from Standby")
                self.syslogger.info("Force create destination directory, ignore error")
                cmd = "mkdir -p "+str(dest_path)
                active_bash_cmd = self.run_bash(cmd = cmd)

                if active_bash_cmd["status"]:
                    self.syslogger.info("Failed to execute bash cmd: \""+str(cmd)+"\" on the Active RP")
                    return {"status" : "error"}
                else:
                    self.syslogger.info("Successfully executed bash cmd: \""+str(cmd)+"\" on the Active RP")
         
                cmd = "ip netns exec xrnns ifconfig eth-vf1.3074 mtu " + str(eth_vf1_mtu) + " && ip netns exec xrnns scp -o StrictHostKeyChecking=no -o ConnectTimeout=300 -r "+str(src_path)+ "/* root@" + str(active_ip) + ":" + str(dest_path)
            else:
                self.syslogger.info("Copying only the source file to target file location")
                cmd = "ip netns exec xrnns ifconfig eth-vf1.3074 mtu " + str(eth_vf1_mtu) + " && ip netns exec xrnns scp -o StrictHostKeyChecking=no -o ConnectTimeout=300 "+str(src_path)+ " root@" + str(active_ip) + ":" + str(dest_path)
            bash_out = self.execute_cmd_on_standby(cmd)

            if bash_out["status"] == "error":
                self.syslogger.info("Failed to transfer file(s) from standby to active")
                return {"status" : "error"}
            else:
                self.syslogger.info("Reset MTU to original value: " +str(ethvf1_MTU)+" on standby")
                cmd = "ip netns exec xrnns ifconfig eth-vf1.3074 mtu "+str(ethvf1_MTU)
                bash_out = self.execute_cmd_on_standby(cmd)

                if bash_out["status"] == "error":
                    self.syslogger.info("Failed to reset MTU on eth-vf1.3074 on standby")
                    cmd = "ip netns exec xrnns ifconfig eth-vf1.3074"
                    bash_out = self.execute_cmd_on_standby(cmd)
    
                    if bash_out["status"] == "error":
                        self.syslogger.info("Failed to fetch eth-vf1.3074 dump from standby")
                    else:
                        self.syslogger.info(bash_out["output"])
                    return {"status" : "error"}
                else:
                    cmd = "ip netns exec xrnns ifconfig eth-vf1.3074"
                    bash_out = self.execute_cmd_on_standby(cmd)

                    if bash_out["status"] == "error":
                        self.syslogger.info("Failed to fetch eth-vf1.3074 dump from standby")
                    else:
                        self.syslogger.info(bash_out["output"])
                    return {"status" : "success"}


    def reload_current_standby(self):
        # Get the current active RP node-name
        exec_cmd = "show redundancy summary"
        show_red_summary = self.xrcmd({"exec_cmd" : exec_cmd})

        if show_red_summary["status"] == "error":
             self.syslogger.info("Failed to get show redundancy summary output from XR")
             return {"status" : "error", "output" : "", "warning" : "Failed to get show redundancy summary output"}

        else:
            try:
                current_standby_rp = show_red_summary["output"][2].split()[1]
            except Exception as e:
                self.syslogger.info("Failed to get Standby RP from show redundancy summary output")
                return {"status" : "error", "output" : "", "warning" : "Failed to get Active RP, error: " + str(e)}

        # Reload standby RP
        exec_cmd = "reload location "+str(current_standby_rp)+" noprompt"
        result = self.xrcmd({"exec_cmd" : exec_cmd})

        if result["status"] == "error":
            self.syslogger.info("Failed to reload Standby RP, please reload manually. Error: "+str(result["output"]))
        else:
            self.syslogger.info("Initiated Standby RP reload. Output: "+str(result["output"]))
        

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', action='append', dest='input_files',
                    help='Specify path of the file to be set up on Standby RP bash shell')
    parser.add_argument('-d', '--directory', action='append', dest='input_directories',
                    help='Specify path of the directories to be set up on Standby RP bash shell')
    parser.add_argument('-c', '--cmd', action='append', dest='standby_bash_cmds',
                    help='Specify the bash commands to be run on standby RP bash shell')
    parser.add_argument('-r', '--standby-rp-reload', action='store_true', dest='standby_rp_reload',
                    help='Reload standby RP')
    parser.add_argument('-m', '--sync-mtu', action='store_true', dest='sync_mtu',
                    help='Set appropriate MTU on sync intf to enable scp of large files to standby and other nodes')
    parser.add_argument('-s', '--standby-to-active', action='store_true', dest='standby_to_active',
                    help='Set this flag combined with -d and/or -f to copy directories and/or files froms standby to active RP')
    parser.add_argument('-v', '--verbose', action='store_true',
                    help='Enable verbose logging')
    

    results = parser.parse_args()
    if results.verbose:
        logger.info("Starting verbose debugging")
        logging.basicConfig()
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)


    xr7l_system_helper = Xr7lSystemHelper()
    #Check if there is a standby RP on the system. If not, abort.

    standby_ip = xr7l_system_helper.standby_rp_ip

    if standby_ip is "":
        xr7l_system_helper.syslogger.info("No standby RP detected or failed to get standby RP xrnns ip. Aborting...")
        sys.exit(0)

    if results.input_files is None:
        xr7l_system_helper.syslogger.info("No input file provided, checking for directories to sync...")
    else:
        for filename in results.input_files:
            # Execute scp_to_standby for each file provided as input
            if results.sync_mtu:
                if results.standby_to_active:
                    scp_output = xr7l_system_helper.scp_from_standby(src_path=os.path.abspath(filename), 
                                                   dest_path=os.path.abspath(filename), 
                                                   sync_mtu=True)
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to scp file: "+str(os.path.abspath(filename))+" from standby to the active RP")
                        sys.exit(1)
                    else:
                        xr7l_system_helper.syslogger.info("Successfully managed to scp file: "+str(os.path.abspath(filename))+" from standby to the active RP")
                else:
                    scp_output = xr7l_system_helper.scp_to_standby(src_path=os.path.abspath(filename), 
                                                   dest_path=os.path.abspath(filename), 
                                                   sync_mtu=True)
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to set up file: "+str(os.path.abspath(filename))+" on the standby RP")
                        sys.exit(1)
                    else:
                        xr7l_system_helper.syslogger.info("Successfully set up file: "+str(os.path.abspath(filename))+" on the standby RP")

            else:
                if results.standby_to_active:
                    scp_output = xr7l_system_helper.scp_from_standby(src_path=os.path.abspath(filename), 
                                                   dest_path=os.path.abspath(filename))
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to scp file: "+str(os.path.abspath(filename))+" from standby to the active RP")
                        sys.exit(1)
                    else:
                        xr7l_system_helper.syslogger.info("Successfully managed to scp file: "+str(os.path.abspath(filename))+" from standby to the active RP")
                else:
                    scp_output = xr7l_system_helper.scp_to_standby(src_path=os.path.abspath(filename), 
                                                   dest_path=os.path.abspath(filename))
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to set up file: "+str(os.path.abspath(filename))+" on the standby RP")
                        sys.exit(1)
                    else:
                        xr7l_system_helper.syslogger.info("Successfully set up file: "+str(os.path.abspath(filename))+" on the standby RP")


    if results.input_directories is None:
        xr7l_system_helper.syslogger.info("No input directories provided...")
    else:
        for dirname in results.input_directories:
            # Execute scp_to_standby for each directory provided as input
            if results.sync_mtu:
                if results.standby_to_active:
                    scp_output = xr7l_system_helper.scp_from_standby(dir_sync=True,
                                                   src_path=os.path.abspath(dirname),
                                                   dest_path=os.path.abspath(dirname),
                                                   sync_mtu=True)
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to scp directory: "+str(os.path.abspath(dirname))+" from standby to the active RP")
                        sys.exit(1)
                    else:                                 
                        xr7l_system_helper.syslogger.info("Successfully managed to scp directory: "+str(os.path.abspath(dirname))+" from standby to the active RP")
                else:
                    scp_output = xr7l_system_helper.scp_to_standby(dir_sync=True,
                                                   src_path=os.path.abspath(dirname),
                                                   dest_path=os.path.abspath(dirname),
                                                   sync_mtu=True)
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to set up directory: "+str(os.path.abspath(dirname))+" on the standby RP")
                        sys.exit(1)
                    else:                                 
                        xr7l_system_helper.syslogger.info("Successfully set up directory: "+str(os.path.abspath(dirname))+" on the standby RP")                   
            else:
                if results.standby_to_active:
                    scp_output = xr7l_system_helper.scp_from_standby(dir_sync=True,
                                                   src_path=os.path.abspath(dirname),
                                                   dest_path=os.path.abspath(dirname))
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to scp directory: "+str(os.path.abspath(dirname))+" from standby to the active RP")
                        sys.exit(1)
                    else:                                 
                        xr7l_system_helper.syslogger.info("Successfully managed to scp directory: "+str(os.path.abspath(dirname))+" from standby to the active RP")

                else:
                    scp_output = xr7l_system_helper.scp_to_standby(dir_sync=True,
                                                   src_path=os.path.abspath(dirname),
                                                   dest_path=os.path.abspath(dirname))
                    if scp_output["status"] == "error":
                        xr7l_system_helper.syslogger.info("Failed to set up directory: "+str(os.path.abspath(dirname))+" on the standby RP")
                        sys.exit(1)
                    else:                                 
                        xr7l_system_helper.syslogger.info("Successfully set up directory: "+str(os.path.abspath(dirname))+" on the standby RP")

    if results.standby_bash_cmds is None:
        xr7l_system_helper.syslogger.info("No Standby RP bash commands provided...")
    else:
        for cmd in results.standby_bash_cmds:
            # Run execute_cmd_on_standby for each bash command provided as input
            standby_bash_cmd = xr7l_system_helper.execute_cmd_on_standby(cmd = cmd)
            
            if standby_bash_cmd["status"] == "error":
                xr7l_system_helper.syslogger.info("Failed to execute bash cmd: \""+str(cmd)+"\" on the standby RP")
                xr7l_system_helper.syslogger.info("Output: \n"+str(standby_bash_cmd["output"])+". Error: "+str(standby_bash_cmd["error"]))
                sys.exit(1)
            else:
                xr7l_system_helper.syslogger.info("Successfully executed bash cmd: \""+str(cmd)+"\" on the standby RP")
                xr7l_system_helper.syslogger.info("Output: \n"+str(standby_bash_cmd["output"]))
             

    if results.standby_rp_reload:
        xr7l_system_helper.syslogger.info("Reloading Standby RP....")
        xr7l_system_helper.reload_current_standby()

    xr7l_system_helper.syslogger.info("Done!")
    sys.exit(0)

