#!/bin/sh
#
# /etc/init.d/setup_vrfforwarding.sh
# Subsystem file for "Vrf forwarding" service
#
# chkconfig: 2345 96 05
# description: Port forwarding across vrfs/netns
#
# processname: VrfForwardingService
# config: /misc/app_host/helpers/vrf_forwarding/config.json
# pidfile: /var/run/vrf_forwarding.pid

# source function library
. /etc/rc.d/init.d/functions

# pull in sysconfig settings

NAME=vrf_forwarding
PIDFILE=/var/run/$NAME.pid
DAEMON="/misc/app_host/installhelpers/vrf_forwarding/vrf_forwarding.py"
DAEMON_INPUT_JSON="/misc/app_host/installhelpers/vrf_forwarding/config.json"
DAEMON_ARGS=" --json-config $DAEMON_INPUT_JSON"
DAEMON_USER="root"

do_start() {
        # Return
        #   0 if daemon has been started
        #   1 if daemon was already running
        #   2 if daemon could not be started
	     echo "Starting port forwarding across vrfs based on input config file"
        if [ -f $PIDFILE ]; then
            echo "VRF forwarding Service already running: see $PIDFILE. Current PID: $(cat $PIDFILE)"
            return 1
        fi

        start-stop-daemon --start --make-pidfile  --background --pidfile $PIDFILE --quiet \
                          --user $DAEMON_USER --startas $DAEMON -- $DAEMON_ARGS \
                          || return 2

        echo "OK"
}

do_stop() {
        # Return
        #   0 if daemon has been stopped
        #   1 if daemon was already stopped
        #   2 if daemon could not be stopped
        #   other if a failure occurred
        start-stop-daemon --signal SIGTERM --stop --quiet --retry=TERM/30/KILL/5 --oknodo --pidfile $PIDFILE -- $DAEMON_ARGS
        RETVAL="$?"
        [ "$RETVAL" = 2 ] && return 2

        rm -f $PIDFILE
        return "$RETVAL"
	      echo "OK"
}


case "$1" in
	start)
		do_start
                case "$?" in
                    0|1) echo -ne "VRF forwarding service started successfully\n"  ;;
                    2) echo -ne "Failed to start VRF forwarding service \n" ;;
                esac
		;;
	stop)
		do_stop
                case "$?" in
                    0|1) echo -ne "VRF forwarding Service stopped successfully\n"  ;;
                    2) echo -ne "Failed to stop VRF forwarding Service \n" ;;
                esac
		;;
	restart)
                echo "Restarting $DESC" "$NAME"
                do_stop
                case "$?" in
                    0|1)
                        echo -ne "VRF forwarding Service stopped successfully.\n"
			do_start
                        case "$?" in
                                0|1) echo "VRF forwarding Service started successfully"  ;;
                                *) echo "Failed to start VRF forwarding Service " ;; # Failed to start
                        esac
                       ;;
                    *)
                       # Failed to stop
                       echo "Failed to stop VRF forwarding Service"
                       exit 1
                    ;;
                esac
                ;;
	*)
		echo "Usage: $0 {start|stop|restart}"
                ;;
esac
exit 0
