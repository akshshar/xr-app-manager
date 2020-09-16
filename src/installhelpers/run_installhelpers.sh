#!/bin/bash
set -x
cwd=`dirname "$(readlink -f "$0")"`
for helper_dir in ${cwd}/*; do
    if [[ -d "$helper_dir" && ! -L "$helper_dir" ]]; then
    	if [[ $helper_dir =~ "helper" ]]; then
            ${helper_dir}/install_helper.sh
        fi
    fi
done
