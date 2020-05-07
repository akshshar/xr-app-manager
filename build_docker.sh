#!/bin/bash

# Clean up mounts
rm -rf /root/RPMS/*
rm -rf /tmp/*

# Build RPM
/usr/sbin/build_rpm.sh -s /usr/src/rpm/SPECS/app_manager.spec