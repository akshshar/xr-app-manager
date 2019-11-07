#!/bin/bash

# Create a custom installation script for your app.
# This script will be run in the post-install stage of the app-manager install.

declare -a ARTIFACT_LIST
declare -a CONFIG_FILE_LIST=("bash_trap.sh" "increment_ipv4_prefix.py" "hosts" "run_openr.sh")

OPENR_CONFIG_DIR="/misc/app_host/openr/"
mkdir -p $OPENR_CONFIG_DIR
OPENR_ARTIFACT_DIR="/misc/disk1/openr/"
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
