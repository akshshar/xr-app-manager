#!/usr/bin/env python

import sys
sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers

import pdb

import os, posixpath, subprocess
import time, json
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
EXIT_FLAG = False

# POSIX signal handler to ensure we shutdown cleanly
def handler(app_manager,signum, frame):
    global EXIT_FLAG

    if not EXIT_FLAG:
        EXIT_FLAG = True
        with open("/misc/app_host/output.txt", "w") as text_file:
            text_file.write("Cleaning up....")
        app_manager.syslogger.info("Cleaning up...")
        sys.exit(0)


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
            with open(self.config_file, 'r') as json_config_fd:
                self.config = json.load(json_config_fd)

        self.setup_apps()
        #self.method_mapper = { 'spin_up_docker' : self.spin_up_docker}
        # Initialize the parent ZtpHelpers class as well


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
             self.sylogger.info("Failed to get show redundancy summary output from XR")
             return {"status" : "error", "output" : "", "warning" : "Failed to get show redundancy summary output"}

        else:
            try:
                current_active_rp = show_red_summary["output"][2].split()[0]
            except Exception as e:
                self.syslogger.info("Failed to get Active RP from show redundancy summary output")
                return {"status" : "error", "output" : "", "warning" : "Failed to get Active RP, error: " + str(e)}

        cmd = "/sbin/ip netns exec xrnns /pkg/bin/node_list_generation -f MY"
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        out, err = process.communicate()
        my_node_name = ''

        if not process.returncode:
            my_node_name = out
        else:
            self.syslogger.info("Failed to get My Node Name")
            

        if current_active_rp.strip() == my_node_name.strip():
            self.syslogger.info("Cron Job: I am the current RP, take action")
            return {"status" : "success", "output" : True, "warning" : ""}    
        else:
            self.syslogger.info("Cron Job: I am not the current RP")
            return {"status" : "error", "output" : False, "warning" : ""} 



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



    def scp_to_standby(self, src_file_path=None, dest_file_path=None):
        """User defined method in Child Class
           Used to scp files from active to standby RP.
           
           leverages the get_peer_rp_ip() method above.
           Useful to keep active and standby in sync with files 
           in the linux environment.
           :param src_file_path: Source file location on Active RP 
           :param dest_file_path: Destination file location on Standby RP 
           :type src_file_path: str 
           :type dest_file_path: str 
           :return: Return a dictionary with status based on scp result. 
                    { 'status': 'error/success' }
           :rtype: dict
        """

        if any([src_file_path, dest_file_path]) is None:
            self.syslogger.info("Incorrect File path\(s\)") 
            return {"status" : "error"}

        standby_ip = self.get_peer_rp_ip()

        if standby_ip["status"] == "error":
            return {"status" : "error"}
        else:
            self.syslogger.info("Transferring file "+str(src_file_path)+" from Active RP to standby location: " +str(dest_file_path))
            cmd = "ip netns exec xrnns scp "+str(src_file_path)+ " root@" + str(standby_ip["peer_rp_ip"]) + ":" + str(dest_file_path)
            bash_out = self.run_bash(cmd)

            if bash_out["status"]:
                self.syslogger.info("Failed to transfer file to standby")
                return {"status" : "error"}
            else:
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
        
        try:
            self.apps = self.config["config"]["apps"]  
            for app in self.apps:
                method_obj = getattr(self, str("manage_")+app["type"]+"_apps")
                app.pop("type")
                method_out = method_obj(**app)
                if method_out["status"] == "error":
                    self.syslogger.info("Error executing method " +str(method_obj.__name__)+ " for app with id: "+ app["app_id"] + ", error:" + method_out["output"])
                    return {"status" : "error", "output" : method_out["output"]}
                else:
                    self.syslogger.info("Result of app setup method:" +str(method_obj.__name__)+" for app with id: "+ app["app_id"] + " is " + method_out["output"])
            return {"status" : "success", "output" : "Successfully executed all cron methods"}
        except Exception as e:
            self.syslogger.info("Failure while setting up apps: " + str(e))
            return {"status" : "error", "output" : str(e)}

            

    def check_docker_running(self, docker_name):
        '''Internal helper method to check if a docker with name docker_name is running
        '''

        cmd = "sudo -i docker ps -f name="+str(docker_name)

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        out, err = process.communicate()

        if not process.returncode:
            docker_state = out 
        else:
            self.syslogger.info("Failed to get docker state")
     
        output_list = []
        output = ''
 
        for line in out.splitlines():
            fixed_line= line.replace("\n", " ").strip()
            output_list.append(fixed_line)
            output = filter(None, output_list)    # Removing empty items

        for line in output:
            if line.split()[-1] == docker_name:
                self.syslogger.info("Docker container " +str(docker_name)+ " is running")
                return {"status" : True}
       
        return {"status" : False}
     

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

    def setup_json_standby():
        # Set up a json file with pointers to local file-based artifacts on current standby during 
        # app_setup on active RP
         
         

    def enable_ha_standby():
        


    def reload_capable():


    def manage_docker_apps(self,
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
                           enable_ha_standby=False,
                           reload_capable=False): 

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

        if self.check_docker_running(docker_container_name)["status"]:
            self.syslogger.info("Skip app bringup, app already running")
            return {"status" : "success", "output" : "Docker container already running"}
        else:      
            image_setup = self.fetch_docker_image(app_id,
                                                  docker_scratch_folder,
                                                  docker_image_name,
                                                  docker_registry,
                                                  docker_image_url,
                                                  docker_image_filepath,
                                                  docker_image_action)
            if image_setup["status"] == "error":
                self.syslogger.info("Failed to set up docker image. Error is " +str(image_setup["output"]))
                return {"status" : "error", "output" : "Failed to set up docker image"}
            else:
                self.syslogger.info("Docker image set up successfully, proceeding with docker bring-up")
                
                container_setup =  self.launch_docker_container(docker_container_name,
                                                                docker_cmd,
                                                                docker_run_misc_options) 
                if container_setup["status"] == "error":
                    self.syslogger.info("Failed to launch the docker app")
                    return {"status" : "error", "output" : "Failed to launch the docker app"}
                else:
                    self.syslogger.info("Docker app successfully launched")
                    # Check if the enable_ha_standby flag is set
                    if enable_ha_standby:
                        # Set up the current (updated) json config file for the app_manager running on standby
                         
                     
    def fetch_docker_image(self,
                           app_id=None,
                           docker_scratch_folder="/tmp",
                           docker_image_name=None,
                           docker_registry=None,
                           docker_image_url=None,
                           docker_image_filepath=None,
                           docker_image_action="import"):

        # Current RP could be active RP during initial deplopyment (registry, url, filepath all OK) or
        # a standby RP that just become active (filepath only option as set up by THEN active RP).
        # Start with filepath first, only then fall to url, then registry.
  
 
        # Copy docker image tarball to scratch folder and load/import it
        try:
            # Start by checking if image filepath is specified
            if docker_image_filepath is not None:
                if self.valid_path(docker_image_path):
                    # Move the file to scratch folder
                    try:
                        import shutil
                        shutil.move(docker_image_path, docker_scratch_folder) 
                        filename = posixpath.basename(docker_image_path) 
                        folder = docker_scratch_folder 
                        filepath = os.path.join(folder, filename)

                        # Update the filepath to reflect the scratch folder location
                        update_app = self.update_docker_config(app_id, key="docker_image_filepath", value=filepath)
                        
                        if update_app["status"] == "error":
                            self.syslogger.info("App_id: "+str(app_id)+"Failed to update app configuration, aborting...")
                            return {"status": "error",  "output" : "App_id: "+str(app_id)+"Failed to update app configuration, aborting..."}
                        else:
                            self.syslogger.info("App_id: "+str(app_id)+"Successfully updated app configuration ")
                    except Exception as e:
                        self.syslogger.info("Failed to copy image to the scratch folder. Error is "+str(e))
                        return {"status": "error",  "output" : "Failed to copy and load docker tarball, bailing out"}
                else: 
                    self.syslogger.info("Docker tarball filepath not valid")
                    return {"status": "error",  "output" : "Unable to copy and load docker tarball, invalid path."}
            elif docker_image_url is not None:
                docker_download = self.download_file(docker_image_path, destination_folder=docker_scratch_folder)
 
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
                cmd = "sudo -i docker import " +str(filepath)+ "  " + str(docker_image_name)
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
                out, err = process.communicate()

                if process.returncode:
                    self.syslogger.info("Failed to import docker image")
                    return {"status" : "error", "output" : "Failed to import docker image"} 
                else:
                    self.syslogger.info("Docker image import command successfully")
            elif docker_image_action == "load":
                cmd = "sudo -i docker load --input " +str(filepath)
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
                out, err = process.communicate()

                if process.returncode:
                    self.syslogger.info("Failed to load docker tarball")
                    return {"status" : "error", "output" : "Failed to load docker tarball"} 
                else: 
                    self.syslogger.info("Docker tarball loaded successfully")


            # Check that the expected docker image is available in local registry
            cmd = "docker inspect --type=image " + str(docker_image_name) + " 2> /dev/null"
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            out, err = process.communicate()

            if process.returncode:
                self.syslogger.info("Failed to inspect docker image")
                return {"status" : "error", "output" : "Failed to inspect docker image"}
            else:
                self.syslogger.info("Docker inspect command successful")
                if docker_image_name in json.loads(out)[0]["RepoTags"]:
                    self.syslogger.info("Docker image with name: "+str(docker_image_name)+" now available") 
                    return {"status" : "success", "output" : "Docker image with name: "+str(docker_image_name)+" now available"} 
                else:
                    self.syslogger.info("Docker image with name: "+str(docker_image_name)+" not available despite successful import/load")
                    return {"status" : "success", "output" : "Docker image with name: "+str(docker_image_name)+" not available despite successful import/load"}
        except Exception as e:
            self.syslogger.info("Failed to load/import Docker image. Error is "+str(e))
            return {"status" : "success", "output" : "Failed to load/import Docker image"}


    def launch_docker_container(self,
                                docker_container_name=None,
                                docker_cmd=None,
                                docker_run_misc_options=None):
        # We don't know why the container died, so remove properly before continuing
        try:
            cmd = "sudo -i docker rm -f "+str(docker_container_name)+ " > /dev/null 2>&1"
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            out, err = process.communicate()
            if process.returncode:
                self.syslogger.info("Failed to run docker rm -f command on dormant container")
                return {"status" : "error", "output" : "Failed to run docker rm -f command on dormant container"}
        except Exception as e:
            self.syslogger.info("Failed to remove dormant container with same name. Error is: " +str(e)) 
            return {"status" : "error", "output" : "Failed to remove dormant container with same name"}

        # Spin up the container
        try:
            cmd = "sudo -i docker run "+ str(docker_run_misc_options)+ " --name " +str(docker_container_name) + " " + str(docker_image_name) + " " + str(docker_cmd) 
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            out, err = process.communicate()
            if process.returncode:
                self.syslogger.info("Failed to spin up the docker container. Error is:" +str(err))
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
        app_manager = AppManager(syslog_server="11.11.11.2",
                                 syslog_port=514,
                                 config_file=json_config_file)

    # Register our handler for keyboard interrupt and termination signals
    signal.signal(signal.SIGINT, partial(handler, app_manager))
    signal.signal(signal.SIGTERM, partial(handler, app_manager))

    # The process main thread does nothing but wait for signals
    signal.pause()
                                                           
