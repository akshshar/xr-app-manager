#!/usr/bin/env python

import sys
sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers

from util.manage_docker_apps import DockerHandler
from util.manage_native_apps import NativeAppHandler
from util.misc import MiscUtils

from util.xr7_system_helper import Xr7Utils


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


class AppManager(ZtpHelpers):

    def __init__(self,
                 syslog_file=None,
                 syslog_server=None,
                 syslog_port=None,
                 config_file=None):

        super(AppManager, self).__init__(syslog_file=syslog_file,
                                         syslog_server=syslog_server,
                                         syslog_port=syslog_port)
        self.docker_handler = DockerHandler(syslog_file=syslog_file,
                                            syslog_server=syslog_server,
                                            syslog_port=syslog_port)
        self.misc_utils = MiscUtils(syslog_file=syslog_file,
                                    syslog_server=syslog_server,
                                    syslog_port=syslog_port)
        self.xr7_utils = Xr7Utils(syslog_file=syslog_file,
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
        self.docker_handler.check_docker_engine(start_wait_time=60, restart_count=1, terminate_count=15)

        self.standby_rp_present = False
        self.poison_pill = False
        self.threadList = []

        for fn in [self.setup_apps]:
            thread = threading.Thread(target=fn, args=())
            self.threadList.append(thread)
            thread.daemon = True                            # Daemonize thread
            thread.start()                                  # Start the execution




 
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

            check_RP_status =  self.xr7_utils.is_active_rp()

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
                    standby_ip = self.xr7_utils.get_peer_rp_ip()

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
                            if str(app["type"]) == "docker":
                                method_obj = getattr(self.docker_handler, str("manage_")+str(app["type"])+"_app")
                            elif str(app["type"]) == "native":
                                method_obj = getattr(self.native_handler, str("manage_")+str(app["type"])+"_app")
                            method_out = method_obj(**app)
                            if method_out["status"] == "error":
                                self.syslogger.info("Error executing method " +str(method_obj.__name__)+ " for app with id: "+ str(app["app_id"]) + ", error:" + method_out["output"])
                            elif method_out["status"] == "success":
                                self.syslogger.info("Result of app manage method: " +str(method_obj.__name__)+" for app with id: "+ str(app["app_id"]) + " is: " + method_out["output"])

                                if app["type"] == "docker":
                                    # Update the filepath to reflect the scratch folder location
                                    update_app = self.update_docker_config(app["app_id"], key="docker_image_filepath", value=str(method_out["docker_image_filepath"]))

                                    if update_app["status"] == "error":
                                        self.syslogger.info("App_id: "+str(app["app_id"])+", Failed to update app configuration, aborting...")
                                        return {"status": "error",  "output" : "App_id: "+str(app["app_id"])+", Failed to update app configuration, aborting..."}
                                    else:
                                        self.syslogger.info("App_id: "+str(app["app_id"])+", Successfully updated app configuration ")

                                
                                if self.standby_rp_present:
                                    # Set up the current (updated) json config file for the app_manager running on standby
                                    json_file_standby = self.setup_json_standby()
                                    if json_file_standby["status"] == "success":
                                        self.syslogger.info("Synced json input file to standby")
                                        return {"status" : "success", "output": "Application successfully launched on Active RP and required artifacts set up on standby RP"}
                                    else:
                                        self.syslogger.info("Failed to sync json input file to standby")
                                else:
                                    return {"status" : "success", "output": "Application successfully launched on Active RP"}


                    except Exception as e:
                        self.syslogger.info("Failure while setting up apps: " + str(e))

            elif check_RP_status["status"] == "error":
                self.syslogger.info("Failed to fetch RP state, try again in next iteration")
            time.sleep(int(APP_MANAGER_LOOP_INTERVAL))




    def setup_json_standby(self):
        # Set up a json file with pointers to local file-based artifacts on current standby during
        # app_setup on active RP

        # Since the input json config file on active RP is updated during setup, just copy over the
        # current updated file to an equivalent location on standby RP.

        # Determine the absolute path of the current config file

        config_file_path = os.path.abspath(self.config_file)
        scp_output = self.xr7_utils.scp_to_standby(src_path=config_file_path,
                                         dest_path=config_file_path)

        if scp_output["status"] == "error":
            self.syslogger.info("Failed to set up json config file on Standby RP")
            return {"status" : "error"}
        else:
            self.syslogger.info("Successfully set up json config file on standby RP")
            return {"status" : "success"}





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
