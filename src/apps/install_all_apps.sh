#!/bin/bash
set -x
cwd=`dirname "$(readlink -f "$0")"`
for app_dir in ${cwd}/*; do
    if [[ -d "$app_dir" && ! -L "$app_dir" ]]; then
        ${app_dir}/install_app.sh
    fi
done
