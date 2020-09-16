# xr-app-manager
A python based application manager that helps automate some recommended guidelines for managing Docker, LXC and native applications on IOS-XR


# Build and Setup instructions

## Setting up the build environment
The RPM build takes place inside a WRL7 docker container published to dockerhub here: <https://cloud.docker.com/u/akshshar/repository/docker/akshshar/xr-wrl7>
The build environment can therefore be orchestrated on either a MacOSX or Linux system that supports bash scripting.

### Dependencies for MacOSX

#### Install greadlink through coreutils

```
brew install coreutils
```

#### Symlink to greadlink to make readlink available

```
macosx:xr-app-manager akshshar$ sudo ln -s /usr/local/bin/greadlink /usr/local/bin/readlink
macosx:xr-app-manager akshshar$ ls -l /usr/local/bin/readlink
lrwxr-xr-x  1 root  admin  24 Oct 18 15:58 /usr/local/bin/readlink -> /usr/local/bin/greadlink
macosx:xr-app-manager akshshar$
```

### Dependencies for Macosx and linux
Install docker on the build machine.
Follow instructions here for the relevant platform:

><https://docs.docker.com/v17.09/engine/installation/>

## Set up app specific details in config.json

### Modify config.json for app_manager to register your app's details

The settings below pertain to two docker applications:  Open/R-on-XR and a simple ubuntu_iproute2 app.

```
macosx:src akshshar$ cd ~/xr-app-manager/src
macosx:src akshshar$
macosx:src akshshar$ cat config.json
{
    "config": {
        "app_manager_loop_interval": "15",
        "apps": [
            {
                "app_id": 1,
                "type": "docker",
                "docker_image_action": "load",
                "docker_scratch_folder": "/misc/disk1/openr/",
                "docker_image_name": "akshshar/openr-xr:latest",
                "docker_image_url": "http://11.11.11.2:9090/openr.tar",
                "docker_mount_volumes": [
                    {
                        "netns_mount": {
                            "host": "/var/run/netns",
                            "container": "/var/run/netns"
                        }
                    },
                    {
                        "config_mount": {
                            "host": "/misc/app_host/openr",
                            "container": "/root/openr"
                        }
                    },
                    {
                        "misc_mounts": [
                            {
                                "host": "",
                                "container": ""
                            },
                            {
                                "host": "",
                                "container": ""
                            },
                            {
                                "host": "",
                                "container": ""
                            }
                        ]
                    }
                ],
                "docker_container_name": "openr",
                "docker_run_misc_options": "-itd --restart=always --cap-add=SYS_ADMIN --cap-add=NET_ADMIN  --hostname rtr1",
                "docker_cmd": "/root/openr/bash_trap.sh route_batch"
            },
            {
                "app_id": 2,
                "type": "docker",
                "docker_image_action": "load",
                "docker_scratch_folder": "/misc/disk1/ubuntu_iproute2",
                "docker_image_name": "akshshar/ubuntu_iproute2_docker:latest",
                "docker_image_filepath": "/misc/disk1/ubuntu_iproute2/ubuntu_iproute2.tar",
                "docker_mount_volumes": [
                    {
                        "netns_mount": {
                            "host": "/var/run/netns",
                            "container": "/var/run/netns"
                        }
                    },
                    {
                        "config_mount": {
                            "host": "/misc/app_host/ubuntu_iproute2",
                            "container": "/root/ubuntu_iproute2"
                        }
                    },
                    {
                        "misc_mounts": [
                            {
                                "host": "",
                                "container": ""
                            },
                            {
                                "host": "",
                                "container": ""
                            },
                            {
                                "host": "",
                                "container": ""
                            }
                        ]
                    }
                ],
                "docker_container_name": "ubuntu_iproute2",
                "docker_run_misc_options": "-itd --restart=always --cap-add=SYS_ADMIN --cap-add=NET_ADMIN  --hostname rtr1",
                "docker_cmd": "bash"
            }
        ]
    }
}
macosx:src akshshar$

```

Some settings are described below:

#### App Manager Loop interval
`app_manager_loop_interval` determines how often app_manager will run. On every iteration, the app_manager will try to spin up the specified apps in config.json on the active RP. It will skip spinning up the apps on standby RP (if present).


#### RP failover State file

`rpfo_state_file` is created by the app_manager for every iteration on active and Standby RPs. This state file can be mounted (see `misc_mounts` below) to make the state file available to your app if it needs it.
`rpfo_state_file` can have three possible states:  `active`, `standby`, `switchover`.

The contents of the `rpfo_state_file` are determined as follows:

*  On Active RP

If last rpfo state was `active`, then app_manager sets it to `active`
If last rpfo state was `standby`, then app_manager sets it to `switchover`
If last rpfo state was `switchover`, then app_manager keeps it set to `switchover`. It is the responsibility of the app to set it to `active`.
If last rpfo state was not present or anything else, then app_manager sets it to `active`.

*  On Standby RP

If last rpfo state was `active`, then app_manager sets it to `standby`
If last rpfo state was `standby`, then app_manager sets it to `standby`
If last rpfo state was `switchover`, then app_manager keeps it set to `standby`
If last rpfo state was not present or anything else, then app_manager sets it to `standby`.


#### Config Mount

The config mount (`config_mount`) is meant to host files that are used as configuration for your app and that you might like synced to the standby RP.
The App manager will sync the entire config_mount folder to the standby RP for every iteration.  In the above example the config mount is located at `/misc/app_host/scratch/config/` on the host/XR-bash environment. This is exposed to the docker container by mounting it to `/root/config` (Set it to whatever the app needs). App manager will sync this folder from `/misc/app_host/scratch/config/` on active RP to `/misc/app_host/scratch/config/` on the Standby RP.

#### Docker image action

`docker_image_action` could be `load` or `import` depending on how you're created the image tarball. This action is only relevant when using `docker_image_filepath` or `docker_image_url` option. In both these cases a tarball is located or downloaded respectively before loading it into the docker database locally on the router.


#### Docker Options

The supported options are:

```
"docker_image_action":  load or import
"docker_scratch_folder": Folder where you'd like to download the docker image tarball
"docker_image_name": Docker image Name expected post load/import
"docker_image_url":  http URL to download the docker image tarball if not packaged.
"docker_image_filepath": Local path to the docker image tarball.
                         "docker_image_filepath" is prefered over "docker_image_url".
                         If filepath does not work, then docker_image_url will be attempted.
"docker_mount_volumes": Specified the mount volumes as a list of key-value pairs.
                        Only the config_mount is unique and will be synced to standby
docker_container_name": Specify the name to be used by your docker application on launch
"docker_run_misc_options": Misc Options cover the rest of the options in the docker run command that are not supported by the above.
                           DO NOT REPEAT the options above in the misc_options here, else the resultant command may fail.
"docker_cmd":  The command to run when the docker container is launched

```

## Set up Application specific artifacts, config files and Install scripts

In the `src/apps` folder, a series of directories corresponding to the apps you'd like to launch are expected.
These directories should ideally be named based on the `app_id` specified in `config.json` above.

For example, in case of the two apps described above in `config.json`,
The following directory structure is set up in `src/apps`:


```
macosx:xr-app-manager akshshar$ tree src/apps
macosx:xr-app-manager akshshar$ tree src/apps/
src/apps/
├── app_id_1
│   ├── bash_trap.sh
│   ├── hosts
│   ├── increment_ipv4_prefix.py
│   ├── install_app.sh
│   └── run_openr.sh
├── app_id_2
│   ├── dummy.config
│   ├── install_app.sh
│   └── ubuntu_iproute2.tar
└── install_all_apps.sh

2 directories, 9 files
macosx:xr-app-manager akshshar$
macosx:xr-app-manager akshshar$

```

**Note**: The ubuntu_iproute2.tar artifact under `/src/apps/app_id_2` is NOT packaged into this repository. This docker image is available on dockerhub at [akshshar/ubuntu_iproute2_docker:latest](https://cloud.docker.com/u/akshshar/repository/docker/akshshar/ubuntu_iproute2_docker).
To obtain this tarball into the app_id_2 directory as shown above, run the following commands:

```
#Pull the docker image on to your build machine

docker pull akshshar/ubuntu_iproute2_docker:latest

# Save the image as a tarball artifact into src/apps/app_id_2/

cd src/apps/app_id_2/
docker save akshshar/ubuntu_iproute2_docker:latest > ubuntu_iproute2.tar

```


Here `install_all_apps.sh` under the `src/apps` directory will invoke all the individual `install_app.sh` script in each app's directory.
For the ubuntu_iproute2 app, the `app_id` in config.json is `2`, so the directory is named `app_id_2`. Within it, the artifacts (ubuntu_iproute2.tar, i.e., the docker image tarball) and all config files (dummy.config- only one in this case. These files should go into config_mount typically).
How and where you choose to put these artifacts as part of install is determined by the `install_app.sh` script in each directory.
For example, a sample installation script is shown below. This script will copy the artifacts to `/run/ubuntu_iproute2/` and the config files to `/misc/app_host/ubuntu_iproute2/`. Modify the script to your liking.

```
macosx:xr-app-manager akshshar$ cd src/apps/
macosx:apps akshshar$ cd app_id_2
macosx:app_id_2 akshshar$
macosx:app_id_2 akshshar$
macosx:app_id_2 akshshar$ cat install_app.sh
#!/bin/bash

# Create a custom installation script for your app.
# This script will be run in the post-install stage of the app-manager install.

declare -a ARTIFACT_LIST=("ubuntu_iproute2.tar")
declare -a CONFIG_FILE_LIST=("dummy.config")

OPENR_CONFIG_DIR="/misc/app_host/ubuntu_iproute2/"
mkdir -p $OPENR_CONFIG_DIR
OPENR_ARTIFACT_DIR="/run/ubuntu_iproute2/"
mkdir -p $OPENR_ARTIFACT_DIR

cwd=`dirname "$(readlink -f "$0")"`

for afct in "${ARTIFACT_LIST[@]}"
do
    echo $afct
    mv ${cwd}/$afct $OPENR_ARTIFACT_DIR/
done

for cfg in "${CONFIG_FILE_LIST[@]}"
do
    echo $cfg
    mv ${cwd}/$cfg $OPENR_CONFIG_DIR/
done
macosx:app_id_2 akshshar$
```


## Build the RPM

Once the `src/apps` directory is set up, time to build the RPM. You can either use the build script or Dockerfile.

### Dockerfile

You can use Docker to build the RPM using two simple commands.

1. `docker build -t xr-app-manager-rpm  .`
   * There are two optional build-args:
      1.  `--build-arg version=<version>` Defaults to "0.1.0".
      2.  `--build-arg release=<release>` Defaults to "XR_6.3.1+".
2. `docker run -it -v $PWD/RPMS:/root/RPMS/ xr-app-manager-rpm`
   1. Add the additonal mount of `-v $PWD/build:/tmp/` to see the build logs.

The final RPM will show up in the folder `$PWD/xr-app-manager/RPMS/x86_64/`.

### Build Script
The build script is located at the root of the git repo called `build_app_manager.sh`.  This script will tar the `src/` directory, mount it into the `akshshar/xr-wrl7` docker image, build the RPM and then create the built rpm into the `RPMS/` directory at the root of the git repo.

The steps are shown below:


```
macosx:xr-app-manager akshshar$ ./build_app_manager.sh
a ../src/apps
a ../src/apps/install_all_apps.sh
a ../src/apps/app_id_2
a ../src/apps/app_id_1
a ../src/apps/app_id_1/install_app.sh
a ../src/apps/app_id_1/increment_ipv4_prefix.py
a ../src/apps/app_id_1/bash_trap.sh
a ../src/apps/app_id_1/hosts
a ../src/apps/app_id_1/run_openr.sh
a ../src/apps/app_id_2/install_app.sh
a ../src/apps/app_id_2/ubuntu_iproute2.tar
a ../src/apps/app_id_2/dummy.config
a ../src/config.json
a ../src/core
a ../src/core/app_manager.pyc
a ../src/core/app_manager.py
a ../src/ha_setup
a ../src/ha_setup/standby_install.py
a ../src/logrotate
a ../src/logrotate/app_manager.conf
a ../src/sysvinit
a ../src/sysvinit/app_manager.sh
80dd5d1f184160570089235475b24295d4db16a3438706a3c4062c2efd03893b

Building . .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
Build process Done!.
Checking artifacts in /Users/akshshar/xr-app-manager/RPMS/x86_64/

-rw-r--r--  1 akshshar  staff  62836106 Oct 31 02:29 /Users/akshshar/xr-app-manager/RPMS/x86_64/xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm

If artifact is not created, check errors in /Users/akshshar/xr-app-manager/tmp/rpmbuild.log
macosx:xr-app-manager akshshar$ scp /Users/akshshar/xr-app-manager/RPMS/x86_64/xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm cisco@10.30.110.215:~/
cisco@10.30.110.215's password:
xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm                                                                            100%   60MB 658.4KB/s   01:33    
macosx:xr-app-manager akshshar$
```

As the logs indicate, if there are any errors during the RPMbuild, then no RPM will be seen in the output above, and one must look at the <>/xr-app-manager/tmp/rpmbuild.log to determine the RPM build errors.

## Copy the RPM to the Router

```shell
[rtr3:~]$
[rtr3:~]$ scp cisco@11.11.11.2:~/xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm ./
cisco@11.11.11.2's password:
xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm     100%   25MB  25.4MB/s   00:01    
[rtr3:~]$

```

## Installing the RPM

Once the RPM is built, copy it over to the router and install using yum install. The spec file is designed to handle the installation on the standby RP as well (if present).

Copy the RPM to the router (use scp from the router shell, or scp to /misc/scratch of the router over XR SSH)
Now install using `yum install`

```
[rtr3:~]$
[rtr3:~]$ yum install -y xr-app-manager-0.1.0-XR_6.3.1+.x86_64
[rtr3:~]$
[rtr3:~]$ yum install -y xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm
Loaded plugins: downloadonly, protect-packages, rpm-persistence
localdb                                                  |  951 B     00:00 ...
Setting up Install Process
Examining xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm: xr-app-manager-0.1.0-XR_6.3.1+.x86_64
Marking xr-app-manager-0.1.0-XR_6.3.1+.x86_64.rpm to be installed
Resolving Dependencies
--> Running transaction check
---> Package xr-app-manager.x86_64 0:0.1.0-XR_6.3.1+ will be installed
--> Finished Dependency Resolution

Dependencies Resolved

================================================================================
 Package    Arch   Version         Repository                              Size
================================================================================
Installing:
 xr-app-manager
            x86_64 0.1.0-XR_6.3.1+ /xr-app-manager-0.1.0-XR_6.3.1+.x86_64 125 M

Transaction Summary
================================================================================
Install       1 Package

Total size: 125 M
Installed size: 125 M
Downloading Packages:
Running Transaction Check
Running Transaction Test
Transaction Test Succeeded
Running Transaction
  Installing : xr-app-manager-0.1.0-XR_6.3.1+.x86_64                        1/1
+++ readlink -f /misc/app_host/apps/install_all_apps.sh
++ dirname /misc/app_host/apps/install_all_apps.sh
+ cwd=/misc/app_host/apps
+ for app_dir in '${cwd}/*'
+ [[ -d /misc/app_host/apps/app_id_1 ]]
+ [[ ! -L /misc/app_host/apps/app_id_1 ]]
+ /misc/app_host/apps/app_id_1/install_app.sh
bash_trap.sh
increment_ipv4_prefix.py
hosts
run_openr.sh
+ for app_dir in '${cwd}/*'
+ [[ -d /misc/app_host/apps/app_id_2 ]]
+ [[ ! -L /misc/app_host/apps/app_id_2 ]]
+ /misc/app_host/apps/app_id_2/install_app.sh
ubuntu_iproute2.tar
dummy.config
+ for app_dir in '${cwd}/*'
+ [[ -d /misc/app_host/apps/install_all_apps.sh ]]
INFO:ZTPLogger:Transferring /etc/rc.d/init.d/app_manager from Active RP to standby location: /etc/rc.d/init.d/app_manager
INFO:ZTPLogger:Copying only the source file to target file location
INFO:ZTPLogger:Successfully set up file: /etc/rc.d/init.d/app_manager on the standby RP
INFO:ZTPLogger:Transferring /usr/sbin/app_manager.py from Active RP to standby location: /usr/sbin/app_manager.py
INFO:ZTPLogger:Copying only the source file to target file location
INFO:ZTPLogger:Successfully set up file: /usr/sbin/app_manager.py on the standby RP
INFO:ZTPLogger:Transferring /etc/logrotate.d/app_manager.conf from Active RP to standby location: /etc/logrotate.d/app_manager.conf
INFO:ZTPLogger:Copying only the source file to target file location
INFO:ZTPLogger:Successfully set up file: /etc/logrotate.d/app_manager.conf on the standby RP
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:No Standby RP bash commands provided...
INFO:ZTPLogger:Done!
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh root@192.0.112.4 "$(< /tmp/tmp7BXRaQ)"
INFO:ZTPLogger:Successfully executed bash cmd: "chkconfig --add app_manager" on the standby RP. Output:
INFO:ZTPLogger:Done!
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh root@192.0.112.4 "$(< /tmp/tmpTKCprM)"
INFO:ZTPLogger:Successfully executed bash cmd: "mkdir -p /etc/app_manager" on the standby RP. Output:
INFO:ZTPLogger:Done!
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:Transferring /etc/app_manager from Active RP to standby location: /etc/app_manager
INFO:ZTPLogger:Copying entire directory and its subdirectories to standby
INFO:ZTPLogger:Successfully set up directory: /etc/app_manager on the standby RP
INFO:ZTPLogger:No Standby RP bash commands provided...
INFO:ZTPLogger:Done!
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh root@192.0.112.4 "$(< /tmp/tmpF7CdMg)"
INFO:ZTPLogger:Successfully executed bash cmd: "mkdir -p /misc/app_host/apps" on the standby RP. Output:
INFO:ZTPLogger:Done!
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:Transferring /misc/app_host/apps from Active RP to standby location: /misc/app_host/apps
INFO:ZTPLogger:Copying entire directory and its subdirectories to standby
INFO:ZTPLogger:Successfully set up directory: /misc/app_host/apps on the standby RP
INFO:ZTPLogger:No Standby RP bash commands provided...
INFO:ZTPLogger:Done!
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh root@192.0.112.4 "$(< /tmp/tmpsa77X5)"
INFO:ZTPLogger:Successfully executed bash cmd: "/misc/app_host/apps/install_all_apps.sh" on the standby RP. Output: bash_trap.sh
increment_ipv4_prefix.py
hosts
run_openr.sh
ubuntu_iproute2.tar
dummy.config

INFO:ZTPLogger:Done!
Restarting  app_manager
App Manager Daemon stopped successfully.
Starting all applications using app_manager
OK
App Manager Daemon started successfully
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh root@192.0.112.4 "$(< /tmp/tmpvHA1la)"
INFO:ZTPLogger:Successfully executed bash cmd: "service app_manager restart" on the standby RP. Output: Restarting  app_manager
App Manager Daemon stopped successfully.
Starting all applications using app_manager
OK
App Manager Daemon started successfully

INFO:ZTPLogger:Done!

Installed:
  xr-app-manager.x86_64 0:0.1.0-XR_6.3.1+                                       

Complete!
[rtr3:~]$
[rtr3:~]$
[rtr3:~]$

```

### Start the App manager

The installation process will automatically start the app manager both on the active and the standby RP.
Since the app_manager is set up as a sysvinit service, if you need to manually start at any point post installation, just run  `service app_manager start`.

## Removing the app_manager

### Stopping the app_manager
Since app_manager is set up as a sysvinit service, to stop it just run `service app_manager stop`


### Uninstalling/Removing the App Manager
To remove app_manager, run `yum remove`. This will also clean up the default directories and files specified in the `%files` section of the app_manager.spec file:

```
%files

%defattr(-,root,root)
%{_sbindir}/app_manager.py
%{_sbindir}/standby_install.py
/etc/app_manager/config.json
/etc/rc.d/init.d/app_manager
/etc/logrotate.d/app_manager.conf
/misc/app_host/apps
```


## Surviving Reloads

The app manager installation also automatically sets up `chkconfig` to ensure app_manager runs on every reload.
Further, even if your app is not designed to restart automatically post a router reload, once you use app_manager to launch it, the app_manager will ensure recovery post reload automatically.


## Install-Helpers

**New Addition**: A new addition to the xr-app-manager architecture is the support for installhelpers - essentially a set of automation scripts and "native" apps that can be installed along with the docker based apps that the xr-app-manager RPM carries. The structure for installhelpers is as follows:


```
aks::~/xr-app-manager$tree src/installhelpers/
src/installhelpers/
├── helper1
│   ├── config.json
│   ├── install_helper.sh
│   ├── setup_vrfforwarding.sh
│   └── vrf_forwarding.py
└── run_installhelpers.sh

1 directory, 5 files
aks::~/xr-app-manager$
```

Under `/src` the installhelpers directory is provided. The user can create their own helper scripts/apps by populating the `helper<id>` directories. 
Note: Only the directories with the name in the format "helper<id>", i.e. helper1, helper2 etc. will be considered by the installation scripts at the time of RPM install.

When the xr-app-manager RPM is installed, the `run_installhelpers.sh` script is run within the `src/installhelpers` directory and this script in turn invokes the `install_helper.sh` script in each helper directory. The user is free to follow any installation technique of their choice as part of the `install_helper.sh` script.

### Install-Helper Example:  VRF Port-forwarding

While the xr-app-manager itself can be used to package, spin-up and manager docker-based apps as described in earlier sections, it is often useful to have native automation/scripting capabilities that could be leveraged at the time of install, and if needed across reloads and RPFOs on the router.

One such use case involves a customer that has the Management interface configured in a Mgmt vrf and has other apps (docker apps, grpc sessions) runnng in the default/global-vrf.
The requirement is to allow the customer to forward the useful sockets/ports from the global-vrf network namespace to the management vrf without any configuration changes required to either leak routes or juggle around with complex features.

For this purpose, we use the following procedure in designing the vrf-port-forwarding helper application:
1) The app creates and manages a pair of virtual interfaces that are part of a "veth-pair" in the XR router's Linux kernel
2) One end of the veth pair resides in one VRF/netns (for e.g. Mgmt vrf)
3) The other end of the veth pair resides in another VRF/netns (for e.g. global-vrf)
4) A /31 private IP address space is selected to configure the 2 ends of the veth-pair that are in different VRFs.
5) A "socat" session is used to port-forward selected sessions (TCP in this case) from one vrf to another using the reachable /31 ip address of the veth peer.
6) The Application is designed to be self sufficient in terms of handling router events such as RPFOs, netns/vrf creation/deletion and reloads.

The basic structure of the helper app can be seen in the `helper1` directory:

```
aks::$ tree src/installhelpers/helper1/
src/installhelpers/helper1/
├── config.json
├── install_helper.sh
├── setup_vrfforwarding.sh
└── vrf_forwarding.py


```

Herein:
    *  `config.json`:   This is a JSON input file for the vrf-forwarding helper application that defines the vrfs, the private ip addresses to use for forwarding and the ports/sockets to forward as part of the socat command.
    *  `install_helper.sh`:  This script is utilized at the time of installation of the xr-app-manager to set up the directory structure for the helper application, move the sysvinit files to the right location and enable chkconfig for the app to withstand router reloads.
    *  `setup_vrfforwading.sh`:  This is the sysvinit script that runs the `vrf_forwarding.py` script as a service across reloads, power-cycles etc.
    *  `vrf_forwarding.py`:  This is the core of the application that takes `config.json` as input, processes the json, sets up the veth-pairs across vrfs and opens up the socat sessions as dictated by the user in config.json.
    
    
 #### Sample Run of vrf_forwarding.py
 
 A sample config.json is provided in the repo for `vrf_forwarding.py` as shown below:
 
 ```
 aks::~/xr-app-manager$cat src/installhelpers/helper1/config.json 
{
    "config": {
        "vrf_forwarding_loop_interval": "15",
        "socat_sessions": [
            {
                "id": "1",
                "source_netns_name" : "blue",
                "source_netns_port" : "57777",
                "dest_netns_ip4" :  "192.168.0.101",
                "dest_netns_port" : "57777",
                "veth_pair": "1"
 
            },
            {
                "id": "2",
                "source_netns_name" : "mgmt",
                "source_netns_port" : "57778",
                "dest_netns_ip4" :  "192.168.0.111",
                "dest_netns_port" : "57777",
                "veth_pair": "2"
            }
        ],
        "veth_pairs": {

            "1" : {
                  "vrf1_name" : "blue", 
                  "vrf2_name" : "global-vrf", 
                  "vrf1_ip_forwarding" : "enable",
                  "vrf2_ip_forwarding" : "enable",
                  "vlnk_number": "0", 
                  "veth_vrf1_ip" :  "192.168.0.100",
                  "veth_vrf2_ip" : "192.168.0.101"
            }, 

            "2" : {
                  "vrf1_name" : "mgmt", 
                  "vrf2_name" : "global-vrf", 
                  "vrf1_ip_forwarding" : "enable",
                  "vrf2_ip_forwarding" : "enable",
                  "vlnk_number": "1", 
                  "veth_vrf1_ip" :  "192.168.0.110",
                  "veth_vrf2_ip" : "192.168.0.111"
            }


        }

    }
}
aks::~/xr-app-manager$
 
 ```
 
The json file helps define the socat_session parameters along with the veth pairs that must be set up before the socat sessions are launched.

When xr-app-manager is installed as an RPM in XR shell, following logs are thrown during the installation (you can modify these to be less verbose if needed):

```

###################   O/P Snipped   #######################


+++ readlink -f /misc/app_host/installhelpers/run_installhelpers.sh
++ dirname /misc/app_host/installhelpers/run_installhelpers.sh
+ cwd=/misc/app_host/installhelpers
+ for helper_dir in '${cwd}/*'
+ [[ -d /misc/app_host/installhelpers/helper1 ]]
+ [[ ! -L /misc/app_host/installhelpers/helper1 ]]
+ [[ /misc/app_host/installhelpers/helper1 =~ helper ]]
+ /misc/app_host/installhelpers/helper1/install_helper.sh
config.json
vrf_forwarding.py
Restarting  vrf_forwarding
VRF forwarding Service stopped successfully.
Starting port forwarding across vrfs based on input config file
OK
VRF forwarding Service started successfully


###################   O/P Snipped   #######################



```

This results in the following directory structure on the router post install:

```
[ios:~]$ tree /misc/app_host/installhelpers/
/misc/app_host/installhelpers/
|-- helper1
|   `-- install_helper.sh
|-- run_installhelpers.sh
`-- vrf_forwarding
    |-- config.json
    `-- vrf_forwarding.py

2 directories, 4 files
[ios:~]$ 


```

with the sysvinit script set up and activated as shown:


```
[ios:~]$ ls -l /etc/init.d/setup_vrfforwarding 
-rwxr-xr-x. 1 root root 3053 Sep 14 06:19 /etc/init.d/setup_vrfforwarding
[ios:~]$ 
[ios:~]$ chkconfig --list setup_vrfforwarding
setup_vrfforwarding	0:off	1:off	2:on	3:on	4:on	5:on	6:off
[ios:~]$ 
[ios:~]$ 
[ios:~]$ ps -ef | grep vrf_forwarding
root     12839     1  0 14:46 ?        00:00:04 python /misc/app_host/installhelpers/vrf_forwarding/vrf_forwarding.py --json-config /misc/app_host/installhelpers/vrf_forwarding/config.json
root     29671 28911  0 15:23 pts/8    00:00:00 grep vrf_forwarding
[ios:~]$ 


```

As an example of the port-forwarding capability, the XR configuration contains the following:

```
RP/0/RP0/CPU0:ios#show running-config vrf
Wed Sep 16 15:23:01.878 UTC
vrf blue
!
vrf mgmt
!

RP/0/RP0/CPU0:ios#show running-config tpa
Wed Sep 16 15:23:08.181 UTC
tpa
 vrf blue
 !
 vrf mgmt
  address-family ipv4
   default-route mgmt
  !
 !
!

RP/0/RP0/CPU0:ios#show running-config grpc
Wed Sep 16 15:23:24.486 UTC
grpc
 port 57777
!

RP/0/RP0/CPU0:ios#


```

GRPC port 57777 is open in the global-vrf network namespace and `config.json` expects the port to be forwarded to VRF/Netns `blue` on port 57777 and to VRF/Netns `mgmt` on port 57778.

Dumping the relevant outputs:

```
[ios:~]$ 
[ios:~]$ netns_identify $$
tpnns
global-vrf
[ios:~]$ 
[ios:~]$ netstat -nlp | grep 57777
tcp        0      0 0.0.0.0:57777           0.0.0.0:*               LISTEN      6942/emsd       
[ios:~]$ 
[ios:~]$ 
[ios:~]$ ip netns exec blue netstat -nlp | grep 57777
tcp        0      0 0.0.0.0:57777           0.0.0.0:*               LISTEN      9153/socat      
[ios:~]$ 
[ios:~]$ 
[ios:~]$ ip netns exec mgmt netstat -nlp | grep 57778
tcp        0      0 0.0.0.0:57778           0.0.0.0:*               LISTEN      9170/socat      
[ios:~]$ 
[ios:~]$ 
[ios:~]$ 


```

As can be seen from the above outputs, port 57777 (emsd process) which is the configured gRPC port in "global-vrf" is forwarded via "socat" processes to VRF "blue" and VRF "mgmt" on ports 57777 and 57778 respectively.

Further, these ports remain up across switchovers, reloads and power-cycles enabling a robust way to access useful sockets over custom VRFs/network-namespaces.


