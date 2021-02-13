#!/usr/bin/env python

import sys
sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers
from misc import MiscUtils
from xr7_system_helper import Xr7Utils

import os, posixpath
import time, json

import logging, logging.handlers
logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)



class DockerHandler(ZtpHelpers):

    def __init__(self,
                 syslog_file=None,
                 syslog_server=None,
                 syslog_port=None):

        super(DockerHandler, self).__init__(syslog_file=syslog_file,
                                         syslog_server=syslog_server,
                                         syslog_port=syslog_port)
        self.misc_utils = MiscUtils(syslog_file=syslog_file,
                                    syslog_server=syslog_server,
                                    syslog_port=syslog_port)
        self.xr7_utils = Xr7Utils(syslog_file=syslog_file,
                                  syslog_server=syslog_server,
                                  syslog_port=syslog_port)

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
                break
            if wait_count > restart_count:
                wait_time=start_wait_time
                wait_count=1
            cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker info"
            docker_engine_status = self.misc_utils.run_bash_timed(cmd, timeout=10)
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


    def check_docker_running(self, docker_name):
        '''Internal helper method to check if a docker with name docker_name is running
        '''

        cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker ps -f name="+str(docker_name)

        docker_status = self.misc_utils.run_bash_timed(cmd, timeout=10)
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
            docker_inspect = self.misc_utils.run_bash_timed(cmd, timeout=10)

            if docker_inspect["status"]:
                self.syslogger.info("Failed to inspect docker image. Output: "+str(docker_inspect["output"])+", Error: "+str(docker_inspect["output"]))
                return {"status" : "error", "output" : "Failed to inspect docker image"}
            else:
                self.syslogger.info("Docker inspect command successful")
                if image_tag in str(json.loads(docker_inspect["output"])[0]["RepoTags"]):
                    self.syslogger.info("Docker image with name: "+str(image_tag)+" now available")
                    return {"status" : "success", "output" : "Docker image with tag: "+str(image_tag)+" is present locally on RP"}



    def remove_docker_app(self,
                          type="docker",
                          app_id=None,
                          docker_scratch_folder='/misc/disk1',
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
                docker_rm = self.misc_utils.run_bash(cmd)
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
                          docker_scratch_folder='/misc/disk1',
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
                            config_mount_sync = self.xr7_utils.scp_to_standby(dir_sync=True,
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
                docker_rm = self.misc_utils.run_bash(cmd)
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
            elif image_setup["status"] == "success":
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
                    return {"status" : "success", "output" : "Docker container successfully launched", 
                            "docker_image_filepath" : str(image_setup["docker_image_filepath"])}



    def fetch_docker_image(self,
                           app_id=None,
                           docker_scratch_folder="/misc/disk1",
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
            rm_image=self.misc_utils.run_bash(cmd)
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
                if self.misc_utils.valid_path(docker_image_filepath):
                    # Move the file to scratch folder
                    try:
                        import shutil
                        filename = posixpath.basename(docker_image_filepath)
                        shutil.move(docker_image_filepath, os.path.join(docker_scratch_folder, filename))
                        folder = docker_scratch_folder
                        filepath = os.path.join(folder, filename)

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


            elif docker_image_url is not None:
                docker_download = self.download_file(docker_image_url, destination_folder=docker_scratch_folder)

                if docker_download["status"] == "error":
                    self.syslogger.info("Failed to download docker container tar ball")
                    return {"status" : "error", "output" : "Failed to download docker tar ball from url"}
                else:
                    filename = docker_download["filename"]
                    folder = docker_download["folder"]
                    filepath = os.path.join(folder, filename)


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
                docker_image_op = self.misc_utils.run_bash(cmd, timeout=10)

                if docker_image_op["status"]:
                    self.syslogger.info("Failed to import docker image. Output: "+str(docker_image_op["output"])+", Error: "+str(docker_image_op["error"]))
                    return {"status" : "error", "output" : "Failed to import docker image"}
                else:
                    self.syslogger.info("Docker image import command ran successfully")
            elif docker_image_action == "load":
                cmd = "export DOCKER_HOST=unix:///misc/app_host/docker.sock && ip netns exec global-vrf docker load --input " +str(filepath)
                docker_image_op = self.misc_utils.run_bash(cmd)

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
                    docker_image_sync_standby = self.xr7_utils.scp_to_standby(src_path=filepath,
                                                                    dest_path=filepath,
                                                                    sync_mtu=True)
                    if docker_image_sync_standby["status"] == "error":
                        self.syslogger.info("Failed to sync docker image to Standby RP")
                        return {"status" : "error"}
                    else:
                        self.syslogger.info("Successfully synced docker image to standby RP")
                        return {"status" : "success", "docker_image_filepath": str(filepath)}
                else:
                    self.syslogger.info("sync_to_standby is off, not syncing docker image tar ball to standby RP")
                    return {"status" : "success"}

                return {"status" : "success", "docker_image_filepath": str(filepath)}
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
        rm_dangling_images=self.misc_utils.run_bash(cmd)
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
            docker_launch = self.misc_utils.run_bash(cmd)

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
