#!/bin/bash

# Create a custom installation script for this helper.
# This script will be run in the post-install stage of the app-manager install, BEFORE any app is installed.
# If you'd like to play with the order in which this script is executed, then make changes to the app_manager.spec 
# file at the root of the repo.

declare -a ARTIFACT_FILE_LIST=("vrf_forwarding.py")
declare -a CONFIG_FILE_LIST=("config.json")

VRF_FORWARDING_DIR="/misc/app_host/installhelpers/vrf_forwarding"
mkdir -p $VRF_FORWARDING_DIR

cwd=`dirname "$(readlink -f "$0")"`

for cfg in "${CONFIG_FILE_LIST[@]}"
do
    echo $cfg
    mv ${cwd}/$cfg $VRF_FORWARDING_DIR/
done

for aft in "${ARTIFACT_FILE_LIST[@]}"
do
    echo $aft
    mv ${cwd}/$aft $VRF_FORWARDING_DIR/
done

# Setup the sysvinit script and start the vrf forwarding helper service
mv ${cwd}/setup_vrfforwarding.sh /etc/init.d/setup_vrfforwarding
chkconfig --add setup_vrfforwarding
service setup_vrfforwarding restart
