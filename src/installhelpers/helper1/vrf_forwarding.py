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


import socket, copy
import logging, logging.handlers
logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)


from ctypes import cdll
libc = cdll.LoadLibrary('libc.so.6')
_setns = libc.setns
CLONE_NEWNET = 0x40000000
#Set default vrf_forwarding loop interval =  15 seconds
VRF_FORWARDING_LOOP_INTERVAL = 15
VRF_FORWARDING_LOOP_INTERVAL_STDBY = 30
EXIT_FLAG = False

# POSIX signal handler to ensure we shutdown cleanly
def handler(vrf_forwarding,signum, frame):
    global EXIT_FLAG

    if not EXIT_FLAG:
        EXIT_FLAG = True
        vrf_forwarding.poison_pill = True

        for thread in vrf_forwarding.threadList:
            vrf_forwarding.syslogger.info("Waiting for %s to finish..." %(thread.name))
            thread.join()
        vrf_forwarding.syslogger.info("Cleaning up...")
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

class VrfForwarding(ZtpHelpers):

    def __init__(self,
                 syslog_file=None,
                 syslog_server=None,
                 syslog_port=None,
                 config_file=None):

        super(VrfForwarding, self).__init__(syslog_file=syslog_file,
                                         syslog_server=syslog_server,
                                         syslog_port=syslog_port)
        if config_file is None:
            self.syslogger.info("No Input config provided, bailing out.... Please provide a compatible json input file")
            sys.exit(1)
        else:
            self.config_file = config_file


        # Read the input config.json file for the first time. It will read periodically in the vrf_forwarding thread as well.
        try:
            with open(self.config_file, 'r') as json_config_fd:
                self.config = json.load(json_config_fd)
        except Exception as e:
            self.syslogger.info("Failed to load config file. Aborting...")
            sys.exit(1)


        self.root_lr_user="ztp-user"
        self.standby_rp_present = False
        self.poison_pill = False
        self.threadList = []

        for fn in [self.setup_port_forwarding]:
            thread = threading.Thread(target=fn, args=())
            self.threadList.append(thread)
            thread.daemon = True                            # Daemonize thread
            thread.start()                                  # Start the execution




    def is_valid_ipv4_address(self, address):
        try:
            socket.inet_pton(socket.AF_INET, address)
        except socket.error:  # not a valid address
            return False
        return True

    def is_valid_ipv6_address(self, address):
        try:
            socket.inet_pton(socket.AF_INET6, address)
        except socket.error:  # not a valid address
            return False
        return True


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
                self.syslogger.info(cmd)
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


    def check_netns(self, netns_name="global-vrf"):
        '''
            Check if a netns is available in the kernel before attempting any netns specific
            operation.

        '''
        try:
            netns_list_op = self.run_bash(cmd="ip netns list")
            if not netns_list_op["status"]:
                netns_list = netns_list_op["output"].split("\n")
                try:
                    if netns_name in netns_list:
                        self.syslogger.info("netns with name: "+str(netns_name)+" is available. Continue with netns operations...")
                        return {"status": "success", "output": True }
                    else:
                        self.syslogger.info("netns with name: "+str(netns_name)+" NOT available.")
                        return {"status": "success", "output": False}
                except Exception as e:
                    self.syslogger.info("Failed to check if netns_name is in current netns list. Error: "+str(e))
                    return {"status": "error", "output": "", "error":"Unable to check netns_name in current netns list, error: "+str(e)}
            else:
                self.syslogger.info("ip netns list command failed, output: "+str(netns_list_op["output"])+"error:"+str(netns_list_op["error"]))       
        except Exception as e:
            self.syslogger.info("Failed to fetch netns list, Error is: "+str(e))
            return {"status": "error", "output": "", "error": "Unable to fetch netns list, error: "+str(e)}


    def enable_vrf_ipv4_forwarding(self, netns_name=None):

        if netns_name is None:
            self.syslogger.info("netns name not specified, aborting...")
            return {"status": "error", "output": False, "error": "netns name not specified, aborting..." }


        try:
            ip_forwarding_enable = self.run_bash(cmd="ip netns exec "+str(netns_name)+" sysctl -w net.ipv4.ip_forward=1")
            if not ip_forwarding_enable["status"]:
                self.syslogger.info("Successfully Enabled IPv4 forwarding for the netns: "+str(netns_name))
                return {"status": "error", "output": True, "error": ""}
            else:
                self.syslogger.info("Failed to Enable IPv4 forwarding for the netns using sysctl")
                return {"status": "error", "output": False, "error": "Failed to Enable IPv4 forwarding for the netns using sysctl" }


        except Exception as e:
            self.syslogger.info("Failed to enable ipv4 forwarding for netns: "+str(netns_name)+". Error: " +str(e))
            return {"status": "error", "output": False, "error": str(e)}


    def disable_vrf_ipv4_forwarding(self, netns_name=None):

        if netns_name is None:
            self.syslogger.info("netns name not specified, aborting...")
            return {"status": "error", "output": False, "error": "netns name not specified, aborting..." }


        try:
            ip_forwarding_enable = self.run_bash(cmd="ip netns exec "+str(netns_name)+" sysctl -w net.ipv4.ip_forward=1")
            if not ip_forwarding_enable["status"]:
                self.syslogger.info("Successfully disabled IPv4 forwarding for the netns: "+str(netns_name))
                return {"status": "error", "output": True, "error": ""}
            else:
                self.syslogger.info("Failed to disable IPv4 forwarding for the netns using sysctl")
                return {"status": "error", "output": False, "error": "Failed to disable IPv4 forwarding for the netns using sysctl" }

        except Exception as e:
            self.syslogger.info("Failed to disable ipv4 forwarding for netns: "+str(netns_name)+". Error: " +str(e))
            return {"status": "error", "output": False, "error": str(e)}

    def create_veth_pair(self, veth1_name=None, veth2_name=None):
        '''
         Blindly create a veth pair requested

        '''

        if veth1_name is None:
            self.syslogger.info("veth1 name not specified, aborting...")
            return {"status": "error", "output": False, "error": "veth1 name not specified, aborting..." }

        if veth2_name is None:
            return {"status": "error", "output": False, "error": "veth2 name not specified, aborting..." }

        try:
            # Create veth pair

            veth_pair_creation = self.run_bash(cmd="ip link add "+str(veth1_name)+ " type veth peer name "+str(veth2_name))

            if not veth_pair_creation["status"]:
                self.syslogger.info("Successfully created veth pair with names: "+ str(veth1_name) + " and "+str(veth2_name))
                return {"status": "success", "output": True, "error": "" }
            else:
                self.syslogger.info("Unable to create veth pair through ip netns add. Error: " + str(veth_pair_creation["error"]) + ", Output: " +str(veth_pair_creation["output"]))
                #return {"status": "error", "error": veth_pair_creation["error"], "output": False}
                return {"status": "success", "output": True, "error": "" }
        except Exception as e:
            self.syslogger.info("Failed to create veth pair. Exception occured, Error: " +str(e))
            return {"status": "error", "error": str(e), "output": False}


    def del_veth_from_netns(self, veth_name=None, netns_name=None):

        if veth_name is None:
            self.syslogger.info("veth name not specified, aborting...")
            return {"status": "error", "output": False, "error": "veth name not specified, aborting..." }

        if netns_name is None:
            self.syslogger.info("netns name not specified, aborting...")
            return {"status": "error", "output": False, "error": "netns name not specified, aborting..." }

        try:

            # Before attempting to delete, check whether veth interface exists in netns

            veth_vrf_check = self.check_veth_in_netns(veth_name=veth_name, netns_name=netns_name)

            if veth_vrf_check["status"] == "success" and veth_vrf_check["output"]:
                self.syslogger.info("veth interface exists in netns, proceeding with delete")
            elif veth_vrf_check["status"] == "success" and not veth_vrf_check["output"]:
                self.syslogger.info("veth interface does not exist in netns, skipping delete...")
                return {"status": "success", "output": True, "error": ""}
            else:
                self.syslogger.info("Unable to determine veth state, skipping delete...")
                return {"status": "error", "output": False, "error": "Unable to determine veth state, skipping delete..."}

            veth_netns_del = self.run_bash(cmd="ip netns exec "+str(netns_name)+" ip link delete "+str(veth_name))
            if not veth_netns_del["status"]:
                check_veth_state = self.check_veth_in_netns(veth_name=veth_name, netns_name=netns_name)
                if check_veth_state["status"] == "error":
                    self.syslogger.info("Successfully deleted veth interface: "+str(veth_name)+" from netns " +str(netns_name))
                    return {"status": "success", "output": True, "error": ""}
                else:
                    self.syslogger.info("Failed to delete veth interface: "+str(veth_name)+" from netns " +str(netns_name)+ " despite successful deletion")
                    return {"status": "error", "error": "Unknown error despite successful deletion", "output": False }
            else:
                self.syslogger.info("Failed to delete veth interface from netns using ip netns delete. Error: " + str(veth_netns_del["error"])+ ", Output: "+str(veth_netns_del["output"]))
                return {"status": "error", "error": str(veth_netns_del["error"]), "output": False }

        except Exception as e:
            self.syslogger.info("Unable to add veth interface to netns/vrf. Exception occured, Error: " +str(e))
            return {"status": "error", "error": str(e), "output": False}


    def check_veth_in_netns(self, veth_name=None, netns_name=None):

        if veth_name is None:
            self.syslogger.info("veth name not specified, aborting...")
            return {"status": "error", "output": False, "error": "veth name not specified, aborting..." }

        if netns_name is None:
            self.syslogger.info("netns name not specified, aborting...")
            return {"status": "error", "output": False, "error": "netns name not specified, aborting..." }


        try:
            # Add veth interface to netns and bring it up
            veth_netns_show = self.run_bash(cmd="ip netns exec "+str(netns_name)+" ip link show "+str(veth_name))

            if not veth_netns_show["status"]:
                self.syslogger.info('veth interface exists in the netns')
                return {"status" : "success", "output": True}

            else:
                return {"status" : "success", "output": False, "error": veth_netns_show["error"]}

        except Exception as e:
            self.syslogger.info("Unable to check if veth interface exists in netns. Exception occured, Error: " +str(e))
            return {"status": "error", "error": str(e), "output": False}


    def add_veth_to_netns(self, veth_name=None, netns_name=None):

        if veth_name is None:
            self.syslogger.info("veth name not specified, aborting...")
            return {"status": "error", "output": False, "error": "veth name not specified, aborting..." }

        if netns_name is None:
            self.syslogger.info("netns name not specified, aborting...")
            return {"status": "error", "output": False, "error": "netns name not specified, aborting..." }

        try:
            # Add veth interface to netns and bring it up
            veth_netns_add = self.run_bash(cmd="ip link set "+str(veth_name)+ " netns "+str(netns_name))
            if not veth_netns_add["status"]:
                self.syslogger.info("Successfully added veth interface: "+str(veth_name)+" to netns " +str(netns_name))
 
                # Bring up veth interface in netns 
                veth_netns_up = self.run_bash(cmd="ip netns exec "+str(netns_name)+ " ip link set dev " +str(veth_name)+ " up")

                if not veth_netns_up["status"]:
                    self.syslogger.info("Successfully brought up veth interface: "+str(veth_name)+" in netns " +str(netns_name))
                    return {"status" : "success", "error": "", "output": True}
                else:
                    self.syslogger.info("Failed to bring up veth interface in netns using ip netns set. Error: " + str(veth_netns_up["error"])+ ", Output: "+str(veth_netns_up["output"]))
                    return {"status": "error", "error": str(veth_netns_up["error"]), "output": False }

            else:
                self.syslogger.info("Failed to add veth interface to netns using ip netns add. Error: " + str(veth_netns_add["error"])+ ", Output: "+str(veth_netns_add["output"]))
                return {"status": "error", "error": str(veth_netns_add["error"]), "output": False }

        except Exception as e:
            self.syslogger.info("Unable to add veth interface to netns/vrf. Exception occured, Error: " +str(e))
            return {"status": "error", "error": str(e), "output": False}



    def assign_ip4_veth_netns(self, ipv4_address=None, veth_name=None, netns_name=None):
        '''
            The subnet/netmask is forced to /31 for any interface allowing only 2 addresses for the veth pair

        '''
        
        if veth_name is None:
            self.syslogger.info("veth name not specified, aborting...")
            return {"status": "error", "output": False, "error": "veth name not specified, aborting..." }

        if netns_name is None:
            self.syslogger.info("netns name not specified, aborting...")
            return {"status": "error", "output": False, "error": "netns name not specified, aborting..." }


        if ipv4_address is None:
            self.syslogger.info("No ipv4 address specified, aborting...")
            return {"status": "error", "output": False, "error": "No ipv4 address specified, aborting..." }
        else:
            if not self.is_valid_ipv4_address(ipv4_address):
                self.syslogger.info("Invalid IPv4 address provided, aborting")
                return {"status": "error", "output": False, "error": "Invalid IPv4 address provided, aborting" }

        try:  
            # Add IP address to veth interface in specified netns
    
            veth_ip_add = self.run_bash(cmd="ip netns exec "+ str(netns_name)+ " ip addr replace "+str(ipv4_address)+"/31 dev "+str(veth_name))

            if not veth_ip_add["status"]:
                self.syslogger.info("Successfully added IP address: "+str(ipv4_address)+" to veth interface: "+str(veth_name)+ " in netns: "+str(netns_name))
                return {"status" : "success", "error": "", "output": True}
            else:
                self.syslogger.info("Failed to assign ip address to veth interface in netns. Error: "+str(veth_ip_add["error"])+", Output: "+str(veth_ip_add["output"]))
                return {"status": "error", "output": False, "error": str(veth_ip_add["error"])}

        except Exception as e:
            self.syslogger.info("Exception occured while attempting to assing ip address to veth interface in netns. Error: "+str(e))
            return {"status": "error", "output": False, "error": str(e)}



    def setup_socat_session(self,
                            source_netns_name=None,
                            source_netns_port=None,
                            dest_netns_ip4=None,
                            dest_netns_port=None):

        if source_netns_name is None:
            self.syslogger.info("source netns name not specified, aborting....")
            return {"status": "error", "error": "source name not specified, aborting....", "output": False}

        if source_netns_port is None:
            self.syslogger.info("source netns port not specified, aborting....")
            return {"status": "error", "error": "source netns port not specified, aborting....", "output": False}

        if dest_netns_ip4 is None:
            self.syslogger.info("destination netns ipv4_address not specified, aborting....")
            return {"status": "error", "error": "destination netns ipv4_address not specified, aborting....", "output": False}

        if dest_netns_port is None:
            self.syslogger.info("destination netns port not specified, aborting....")
            return {"status": "error", "error": "destination netns port not specified, aborting....", "output": False}

        try:
            # Set up port forwarding for a TCP session originating in destination netns with veth linkpair already created

            cmd="ip netns exec "+ str(source_netns_name)+ " nohup socat tcp-listen:"+str(source_netns_port)+",reuseaddr,fork tcp-connect:"+str(dest_netns_ip4)+":"+str(dest_netns_port)+" >/dev/null 2>&1 &"
            socket_create = self.run_bash(cmd=cmd)

            self.syslogger.info(socket_create)
            if not socket_create["status"]:
                self.syslogger.info("Successfully created socat session")
                return {"status": "success",  "error" : "", "output": True}

            else:
                self.syslogger.info("Failed to create socat. Error: "+str(socket_create["error"])+", Output: "+str(socket_create))
                return {"status": "error", "error": str(socket_create["error"]), "output": False}
        except Exception as e:
            self.syslogger.info("Exception occured while trying to create socat. Error: "+str(e))
            return {"status": "error", "error": str(e), "output": False}




    def setup_veth_across_vrfs(self, 
                              vrf1_name=None, 
                              vrf2_name=None, 
                              vlnk_number="0", 
                              veth_vrf1_name=None, 
                              veth_vrf2_name=None,
                              veth_vrf1_ip=None,
                              veth_vrf2_ip=None,
                              vrf1_ip_forwarding=False,
                              vrf2_ip_forwarding=False):
        '''
            Set up a veth pair across two specified netns/vrfs.
            The Default naming convention selected for veth link will be:
            vlnk<number>_<vrf2_name> inside vrf1
            and 
            vlnk<number>_<vrf1_name> inside vrf2
            to clearly depict which vrf a particular veth link connects to 
            from a given vrf.
            The number is vlnk_number which is by default 0 and can be set to any
            value based on the user choice. The same number gets used at both ends
            of the veth pair.
            Disclaimer: No attempt is made by this method to do any conflict resolution
            in case a veth link cannot be created because the links are already created. 
            An error will simply be relayed back. 

        '''


        if vrf1_name is None:
            self.syslogger.info("vrf1 name not specified, aborting....")
            return {"status": "error", "error": "vrf1 name not specified, aborting....", "output": False}
        else:
            check_vrf1 = self.check_netns(netns_name=vrf1_name)
            if check_vrf1["status"] == "success" and check_vrf1["output"]:
                self.syslogger.info("netns "+str(vrf1_name)+" is available")
            else:
                self.syslogger.info("netns "+str(vrf1_name)+" is not available. Wait for next iteration...")
                return {"status": "error", "error": "netns "+str(vrf1_name)+" is not available", "output": False}



        if vrf2_name is None:
            self.syslogger.info("vrf2 name not specified, aborting....")
            return {"status": "error", "error": "vrf2 name not specified, aborting....", "output": False}
        else:
            check_vrf2 = self.check_netns(netns_name=vrf2_name)
            if check_vrf2["status"] == "success" and check_vrf2["output"]:
                self.syslogger.info("netns "+str(vrf2_name)+" is available")
            else:
                self.syslogger.info("netns "+str(vrf2_name)+" is not available. Wait for next iteration...")
                return {"status": "error", "error": "netns "+str(vrf2_name)+" is not available", "output": False}



        if veth_vrf1_name is None:
            veth_vrf1_name_full = "vlnk"+str(vlnk_number)+"_"+str(vrf2_name)
            veth_vrf1_name = veth_vrf1_name_full[0:14] #Linux kernel supports max length of 15 characters for interface names
            self.syslogger.info("veth_vrf1 interface name not specified, setting to default value: "+str(veth_vrf1_name))

        if veth_vrf2_name is None:
            veth_vrf2_name_full = "vlnk"+str(vlnk_number)+"_"+str(vrf1_name)
            veth_vrf2_name = veth_vrf2_name_full[0:14] #Linux kernel supports max length of 15 characters for interface names
            self.syslogger.info("veth_vrf2 interface name not specified, setting to default value: "+str(veth_vrf2_name))

        if veth_vrf1_ip is None:
            self.syslogger.info("veth_vrf1 ip not specified, aborting....")
            return {"status": "error", "error": "veth_vrf1 ip not specified, aborting", "output": False}


        if veth_vrf2_ip is None:
            self.syslogger.info("veth_vrf2 ip not specified, aborting....")
            return {"status": "error", "error": "veth_vrf2 ip not specified, aborting", "output": False}


        if vrf1_ip_forwarding == "enable":
            ip_fwd_enable = self.enable_vrf_ipv4_forwarding(netns_name=vrf1_name)

            if ip_fwd_enable["status"] == "success" and ip_fwd_enable["output"]:
                self.syslogger.info("IPv4 forwarding enabled for vrf: "+str(vrf1_name))
            else:
                self.syslogger.info("Failed to enable IPv4 forwarding for vrf: "+str(vrf1_name))
        elif vrf1_ip_forwarding == "disable":
            ip_fwd_disable = self.disable_vrf_ipv4_forwarding(netns_name=vrf1_name)

            if ip_fwd_disable["status"] == "success" and ip_fwd_disable["output"]:
                self.syslogger.info("IPv4 forwarding disabled for vrf: "+str(vrf1_name))
            else:
                self.syslogger.info("Failed to disable IPv4 forwarding for vrf: "+str(vrf1_name))


        if vrf2_ip_forwarding == "enable":
            ip_fwd_enable = self.enable_vrf_ipv4_forwarding(netns_name=vrf2_name)

            if ip_fwd_enable["status"] == "success" and ip_fwd_enable["output"]:
                self.syslogger.info("IPv4 forwarding enabled for vrf: "+str(vrf2_name))
            else:
                self.syslogger.info("Failed to enable IPv4 forwarding for vrf: "+str(vrf2_name))
        elif vrf2_ip_forwarding == "disable":
            ip_fwd_disable = self.disable_vrf_ipv4_forwarding(netns_name=vrf2_name)

            if ip_fwd_disable["status"] == "success" and ip_fwd_disable["output"]:
                self.syslogger.info("IPv4 forwarding disabled for vrf: "+str(vrf2_name))
            else:
                self.syslogger.info("Failed to disable IPv4 forwarding for vrf: "+str(vrf2_name))


        # First check if veth interface already exists in netns

        veth1_vrf1_check = self.check_veth_in_netns(veth_name=veth_vrf1_name, netns_name=vrf1_name)
        veth2_vrf2_check = self.check_veth_in_netns(veth_name=veth_vrf2_name, netns_name=vrf2_name)
 
        if (veth1_vrf1_check["status"] == "success" and 
            veth1_vrf1_check["output"] and
            veth2_vrf2_check["status"] == "success" and 
            veth2_vrf2_check["output"]):

            self.syslogger.info("veth interfaces already exist in respective netns. Skip to ip address assignment...")
        else:
            # Either one or both veth interfaces do not exist in required netns
            # First issue a delete for both the veth interfaces before proceeding with recreation

            veth1_vrf1_delete = self.del_veth_from_netns(veth_name=veth_vrf1_name, netns_name=vrf1_name)
            veth2_vrf2_delete = self.del_veth_from_netns(veth_name=veth_vrf1_name, netns_name=vrf1_name)

            if veth1_vrf1_delete["status"] == "success" and veth2_vrf2_delete["status"] == "success":
                self.syslogger.info("Successfully deleted both veth interfaces before recreation")

                veth_pair_creation = self.create_veth_pair(veth1_name=veth_vrf1_name, veth2_name=veth_vrf2_name)

                if veth_pair_creation["status"] == "success" and veth_pair_creation["output"]:

                    # Add veths to respective netns
                    veth_vrf1_add = self.add_veth_to_netns(veth_name=veth_vrf1_name, netns_name=vrf1_name)
                    if veth_vrf1_add["status"] == "success" and veth_vrf1_add["output"]:

                        veth_vrf2_add = self.add_veth_to_netns(veth_name=veth_vrf2_name, netns_name=vrf2_name)

                        if veth_vrf2_add["status"] == "success" and veth_vrf2_add["output"]:
                            self.syslogger.info("Both interfaces Successfully created in respective netns, proceed with ip address assignment")
                        else:
                            self.syslogger.info("Failed to add veth to netns vrf2. Response: " + str(veth_vrf2_add))
                            return {"status": "error", "error": str(veth_vrf2_add["error"]), "output": False}
                    else:
                
                        self.syslogger.info("Failed to add veth to netns vrf1. Response: " + str(veth_vrf1_add))
                        return {"status": "error", "error": str(veth_vrf1_add["error"]), "output": False}     
                else:
                    self.syslogger.info("Failed to create veth pair. Response: " + str(veth_pair_creation))
                    return {"status": "error", "error": str(veth_pair_creation["error"]), "output": False}          

        # Assign IP addresses to veth interfaces

        veth_vrf1_ip = self.assign_ip4_veth_netns(ipv4_address=veth_vrf1_ip, veth_name=veth_vrf1_name, netns_name=vrf1_name)
        if veth_vrf1_ip["status"] == "success" and veth_vrf1_ip["output"]:
            veth_vrf2_ip = self.assign_ip4_veth_netns(ipv4_address=veth_vrf2_ip, veth_name=veth_vrf2_name, netns_name=vrf2_name)

            if veth_vrf2_ip["status"] == "success" and veth_vrf2_ip["output"]:
                self.syslogger.info("Successfully set up veth pairs with ipv4 addresses across vrfs/netns")
                return {"status": "success", "error":"", "output": True}
            else: 
                self.syslogger.info("Failed to add ip to veth in netns vrf1. Response: " + str(veth_vrf2_ip))
                return {"status": "error", "error": str(veth_vrf2_ip["error"]), "output": False}
        else:
            self.syslogger.info("Failed to add ip to veth in netns vrf1. Response: " + str(veth_vrf1_ip))
            return {"status": "error", "error": str(veth_vrf1_ip["error"]), "output": False}
                      

   




    def setup_port_forwarding(self):
        '''
           Eventually may support multiple input methods. Currently supports the input
           json file for method_list and parameters.
        '''

        global VRF_FORWARDING_LOOP_INTERVAL
        global VRF_FORWARDING_LOOP_INTERVAL_STDBY
       # This method is started as a daemon thread.
       # Keeps running a loop to automatically load an updated json config file if it changes

        while True:
            self.syslogger.info("Back to the top...")
            # Look for a poison pill in case of termination
            if self.poison_pill:
                self.syslogger.info("Received poison pill, terminating port forwarding setup thread")
                return

            try:
            # Periodically load up config file to accomodate changes as part of the main thread loop
                with open(self.config_file, 'r') as json_config_fd:
                    self.config = json.load(json_config_fd)
            except Exception as e:
                self.syslogger.info("Failed to load config file. Sleep and retry")
                time.sleep(60)
                continue


            # Only try to set up port forwarding on an active RP

            check_RP_status =  self.is_active_rp()

            if check_RP_status["status"] == "success":
                if not check_RP_status["output"]:
                    # Currently on Standby RP, wait and go back to start of loop
                    self.syslogger.info("Currently running on Standby RP, skipping action. Sleep and Retry")

                    if "vrf_forwarding_loop_interval_stdby" in list(self.config["config"].keys()):
                        VRF_FORWARDING_LOOP_INTERVAL_STDBY = self.config["config"]["vrf_forwarding_loop_interval_stdby"]

                    self.syslogger.info("Sleeping for seconds: "+str(VRF_FORWARDING_LOOP_INTERVAL_STDBY))
                    time.sleep(int(VRF_FORWARDING_LOOP_INTERVAL_STDBY))
                    continue
                else:
                    self.syslogger.info("Currently running on Active RP, perform action")

                    try:
                        if "vrf_forwarding_loop_interval" in list(self.config["config"].keys()):
                            VRF_FORWARDING_LOOP_INTERVAL = self.config["config"]["vrf_forwarding_loop_interval"]

                        self.socat_sessions = self.config["config"]["socat_sessions"]
                        for socat_session in self.socat_sessions:
                            #First create the veth pair dependency
                            veth_pair = self.config["config"]["veth_pairs"][socat_session["veth_pair"]]
                            method_obj = getattr(self, "setup_veth_across_vrfs")
                            method_out = method_obj(**veth_pair)
                            if method_out["status"] == "error":
                                self.syslogger.info("Error executing method " +str(method_obj.__name__)+ " for socat session with id: "+ str(socat_session["id"]) + ", error:" + str(method_out["error"]))
                            else:
                                #self.syslogger.info("Result of veth_pair_creation method: " +str(method_obj.__name__)+" for socat session with id: "+ str(socat_session["id"]) + " is: " + str(method_out["output"]))
                                
                                socat_session_temp = copy.deepcopy(socat_session)
                                if "id" in socat_session_temp:
                                    del socat_session_temp["id"]
                                if "veth_pair" in socat_session_temp:
                                    del socat_session_temp["veth_pair"]

                                 # Now start the socat session
                                print(socat_session_temp)
                                method_obj = getattr(self, "setup_socat_session")
                                method_out = method_obj(**socat_session_temp)
                                if method_out["status"] == "error":
                                    self.syslogger.info("Error executing method " +str(method_obj.__name__)+ " for socat session with id: "+ str(socat_session["id"]) + ", error:" + str(method_out["error"]))
                                else:
                                    self.syslogger.info("Result of socat session creation method: " +str(method_obj.__name__)+" for socat session with id: "+ str(socat_session["id"]) + " is: " + str(method_out["output"]))
                               
                    except Exception as e:
                        self.syslogger.info("Failure while performing action: " + str(e))

            elif check_RP_status["status"] == "error":
                self.syslogger.info("Failed to fetch RP state, try again in next iteration")
            time.sleep(int(VRF_FORWARDING_LOOP_INTERVAL))



if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--json-config', action='store', dest='json_config',
                    help='Specify the JSON file describing port forwarding metadata metadata')
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
        vrf_forwarding = VrfForwarding(syslog_file="/var/log/vrf_forwarding",
                                       config_file=results.json_config)

    # Register our handler for keyboard interrupt and termination signals
    signal.signal(signal.SIGINT, partial(handler, vrf_forwarding))
    signal.signal(signal.SIGTERM, partial(handler, vrf_forwarding))

    # The process main thread does nothing but wait for signals
    signal.pause()

    sys.exit(0)
