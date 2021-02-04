
# Testing xr7l_system_helper.py

## Copy the system helper script to a Dual RP XR7 system (Cisco8000 or NCS540):

The following command will copy xr7l_system_helper.py to disk0:/ of the router. ( OR you could use the "copy" CLI in XR to download the file to the router disk0:)
```
scp <file_path>/xr7l_system_helper.py  rtr_user@<rtr_ip>:/disk0\:/
```
The file can be viewed on the router by dropping into XR bash using the "bash" cli:

```
RP/0/RP0/CPU0:ios#bash
Thu Feb  4 09:38:03.348 UTC
[ios:~]$
[ios:~]$cd /disk0\:/
[ios:/disk0:]$
[ios:/disk0:]$ls -l xr7l_system_helper.py 
-rw-r--r--. 1 root root 34797 Feb  4 09:09 xr7l_system_helper.py
[ios:/disk0:]$
[ios:/disk0:]$
[ios:/disk0:]$
```

## Create a test directory and test file on Active RP

```
[ios:/disk0:]$
[ios:/disk0:]$
[ios:/disk0:]$mkdir active_test_dir
[ios:/disk0:]$echo "Active RP test file" > active_test_dir/active_test.txt
[ios:/disk0:]$
[ios:/disk0:]$ls -l /disk0\:/active_test_dir/
total 4
-rw-r--r--. 1 root root 20 Feb  4 09:09 active_test.txt
[ios:/disk0:]$
```

## View the available options 

```
[ios:/disk0:]$python xr7l_system_helper.py -h
# netconf_client_ztp_lib - version 1.1 #
usage: xr7l_system_helper.py [-h] [-s] [-f INPUT_FILES] [-d INPUT_DIRECTORIES]
                             [-c STANDBY_BASH_CMDS] [-r] [-m] [-v]

optional arguments:
  -h, --help            show this help message and exit
  -s, --standby-to-active
                        Set this flag combined with -d and/or -f to copy
                        directories and/or files froms standby to active RP.
                        By default, all files and directories are copied from
                        Active RP to Standby RP
  -f INPUT_FILES, --file INPUT_FILES
                        Specify path of the file to be set up on Active or
                        Standby RP bash shell
  -d INPUT_DIRECTORIES, --directory INPUT_DIRECTORIES
                        Specify path of the directories to be set up on Active
                        or Standby RP bash shell
  -c STANDBY_BASH_CMDS, --cmd STANDBY_BASH_CMDS
                        Specify the bash commands to be run on standby RP bash
                        shell
  -r, --standby-rp-reload
                        Reload standby RP
  -m, --sync-mtu        Set appropriate MTU on sync intf to enable scp of
                        large files to standby and other nodes
  -v, --verbose         Enable verbose logging
[ios:/disk0:]$

```


## Use "-c" option to run commands on Standby RP

Here we check if "active_test_dir" already exists on the Standby RP or not:

```
[ios:/disk0:]$python xr7l_system_helper.py -c "ls /disk0\:/active_test_dir/"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmpUsHeqn)"
INFO:ZTPLogger:Failed to execute command on standby
INFO:ZTPLogger:Failed to execute bash cmd: "ls /disk0\:/active_test_dir/" on the standby RP
INFO:ZTPLogger:Output: 
. Error: ls: cannot access '/disk0:/active_test_dir/': No such file or directory

[ios:/disk0:]$
```


## Use the "-d" option to scp an entire directory (from Active RP to Standby RP, by default):

```
[ios:/disk0:]$python xr7l_system_helper.py -d /disk0\:/active_test_dir/
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:Transferring /disk0:/active_test_dir from Active RP to standby location: /disk0:/active_test_dir
INFO:ZTPLogger:Setting eth-vf1.3074 MTU to 9400 for scp commands
INFO:ZTPLogger:Copying entire directory and its subdirectories to standby
INFO:ZTPLogger:Force create destination directory, ignore error
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmpVE1xnu)"
INFO:ZTPLogger:Successfully executed bash cmd: "mkdir -p /disk0:/active_test_dir" on the standby RP. Output: 
INFO:ZTPLogger:Reset MTU to original value: 9400
INFO:ZTPLogger:eth-vf1.3074 Link encap:Ethernet  HWaddr 4e:41:50:00:1e:01  
          inet addr:172.0.30.1  Bcast:172.255.255.255  Mask:255.0.0.0
          UP BROADCAST RUNNING ALLMULTI MULTICAST  MTU:9400  Metric:1
          RX packets:263703 errors:0 dropped:0 overruns:0 frame:0
          TX packets:291252 errors:0 dropped:0 overruns:0 carrier:0
          collisions:0 txqueuelen:1000 
          RX bytes:42043934 (40.0 MiB)  TX bytes:68598797 (65.4 MiB)


INFO:ZTPLogger:Successfully set up directory: /disk0:/active_test_dir on the standby RP
INFO:ZTPLogger:No Standby RP bash commands provided...
INFO:ZTPLogger:Done!
[ios:/disk0:]$
```


## Use the "-c" option to check created directories/files on Standby RP

```
[ios:/disk0:]$
[ios:/disk0:]$python xr7l_system_helper.py -c "ls -l /disk0\:/active_test_dir/"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmppzcyRL)"
INFO:ZTPLogger:Successfully executed bash cmd: "ls -l /disk0\:/active_test_dir/" on the standby RP
INFO:ZTPLogger:Output: 
total 4
-rw-r--r--. 1 root root 20 Feb  4 09:10 active_test.txt

INFO:ZTPLogger:Done!
[ios:/disk0:]$python xr7l_system_helper.py -c "ls -l /disk0\:/active_test_dir/"^C
[ios:/disk0:]$
[ios:/disk0:]$
[ios:/disk0:]$python xr7l_system_helper.py -c "cat /disk0\:/active_test_dir/*"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmpWNkWf9)"
INFO:ZTPLogger:Successfully executed bash cmd: "cat /disk0\:/active_test_dir/*" on the standby RP
INFO:ZTPLogger:Output: 
Active RP test file

INFO:ZTPLogger:Done!
[ios:/disk0:]$
[ios:/disk0:]$
```


## Use the "-c" option to create a new file on Standby RP

```
[ios:/disk0:]$
[ios:/disk0:]$python xr7l_system_helper.py -c "echo \"Standby test file\" > /disk0\:/active_test_dir/standby_test.txt"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmp59op1i)"
INFO:ZTPLogger:Successfully executed bash cmd: "echo "Standby test file" > /disk0\:/active_test_dir/standby_test.txt" on the standby RP
INFO:ZTPLogger:Output: 

INFO:ZTPLogger:Done!
[ios:/disk0:]$
[ios:/disk0:]$
```

## Use the "-c" option to dump the latest directory state on Standby RP

```
[ios:/disk0:]$
[ios:/disk0:]$python xr7l_system_helper.py -c "ls /disk0\:/active_test_dir/"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmplZQ_wU)"
INFO:ZTPLogger:Successfully executed bash cmd: "ls /disk0\:/active_test_dir/" on the standby RP
INFO:ZTPLogger:Output: 
active_test.txt
standby_test.txt

INFO:ZTPLogger:Done!
[ios:/disk0:]$
[ios:/disk0:]$
[ios:/disk0:]$
[ios:/disk0:]$python xr7l_system_helper.py -c "ls -l /disk0\:/active_test_dir/"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmp33SVtq)"
INFO:ZTPLogger:Successfully executed bash cmd: "ls -l /disk0\:/active_test_dir/" on the standby RP
INFO:ZTPLogger:Output: 
total 8
-rw-r--r--. 1 root root 20 Feb  4 09:10 active_test.txt
-rw-r--r--. 1 root root 18 Feb  4 09:11 standby_test.txt

INFO:ZTPLogger:Done!
[ios:/disk0:]$
```

# Check the latest Directory state on Active RP

```
[ios:/disk0:]$
[ios:/disk0:]$ls -l /disk0\:/active_test_dir/
total 4
-rw-r--r--. 1 root root 20 Feb  4 09:09 active_test.txt
[ios:/disk0:]$
```

## Use the "-s" option along with the "-d" option to do reverse copy (from Standby RP to Active RP):

```
[ios:/disk0:]$python xr7l_system_helper.py -s -d /disk0\:/active_test_dir/
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:Transferring /disk0:/active_test_dir from Standby RP to Active RP location: /disk0:/active_test_dir
INFO:ZTPLogger:Setting eth-vf1.3074 MTU on Standby to 9400 for scp commands
INFO:ZTPLogger:Copying entire directory and its subdirectories to Active from Standby
INFO:ZTPLogger:Force create destination directory, ignore error
INFO:ZTPLogger:Successfully executed bash cmd: "mkdir -p /disk0:/active_test_dir" on the Active RP
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmpYagZff)"
INFO:ZTPLogger:Reset MTU to original value: 9400 on standby
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmp1w4e7a)"
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmp7rkLo3)"
INFO:ZTPLogger:eth-vf1.3074 Link encap:Ethernet  HWaddr 4e:41:50:00:1f:01  
          inet addr:172.0.31.1  Bcast:172.255.255.255  Mask:255.0.0.0
          UP BROADCAST RUNNING ALLMULTI MULTICAST  MTU:9400  Metric:1
          RX packets:296190 errors:0 dropped:0 overruns:0 frame:0
          TX packets:260096 errors:0 dropped:0 overruns:0 carrier:0
          collisions:0 txqueuelen:1000 
          RX bytes:60834237 (58.0 MiB)  TX bytes:41776888 (39.8 MiB)


INFO:ZTPLogger:Successfully managed to scp directory: /disk0:/active_test_dir from standby to the active RP
INFO:ZTPLogger:No Standby RP bash commands provided...
INFO:ZTPLogger:Done!
[ios:/disk0:]$
```


## Check the latest Directory state on Active RP post a reverse scp

```
[ios:/disk0:]$
[ios:/disk0:]$ls -l /disk0\:/active_test_dir/
total 8
-rw-r--r--. 1 root root 20 Feb  4 09:16 active_test.txt
-rw-r--r--. 1 root root 18 Feb  4 09:16 standby_test.txt
[ios:/disk0:]$
[ios:/disk0:]$cat active_test_dir/standby_test.txt
Standby test file
[ios:/disk0:]$
[ios:/disk0:]$
```


## Clean up on Active RP

```
[ios:/disk0:]$
[ios:/disk0:]$rm -r active_test_dir/
[ios:/disk0:]$
```

## Clean up on Standby RP

```
[ios:/disk0:]$
[ios:/disk0:]$python xr7l_system_helper.py -c "rm -r /disk0\:/active_test_dir/"
# netconf_client_ztp_lib - version 1.1 #
INFO:ZTPLogger:Standby RP is present
INFO:ZTPLogger:I am the current RP, take action
INFO:ZTPLogger:Running on active RP
source /pkg/etc/xr_startup_envs.sh && ip netns exec xrnns /pkg/bin/nodename_to_ipaddress -n 0/RP0/CPU0 2>&1
INFO:ZTPLogger:No input file provided, checking for directories to sync...
INFO:ZTPLogger:No input directories provided...
INFO:ZTPLogger:Standby cmd: ip netns exec xrnns ssh -o StrictHostKeyChecking=no root@172.0.31.1 "$(< /tmp/tmpM8aR2s)"
INFO:ZTPLogger:Successfully executed bash cmd: "rm -r /disk0\:/active_test_dir/" on the standby RP
INFO:ZTPLogger:Output: 

INFO:ZTPLogger:Done!
[ios:/disk0:]$
[ios:/disk0:]$
```
