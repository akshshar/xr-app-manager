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
                "docker_scratch_folder": "/run/openr/",
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
                "docker_scratch_folder": "/run/ubuntu_iproute2",
                "docker_image_name": "akshshar/ubuntu_iproute2_docker:latest",
                "docker_image_filepath": "/run/ubuntu_iproute2/ubuntu_iproute2.tar",
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
