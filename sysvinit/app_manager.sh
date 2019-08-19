#!/bin/sh
#
# /etc/init.d/app_manager
# Subsystem file for "App Manager" Daemon
#
# chkconfig: 2345 95 05
# description: Application Manager Daemon
#
# processname: AppManager
# config: /etc/app_manager/config.json
# pidfile: /var/run/app_manager.pid

# source function library
. /etc/rc.d/init.d/functions

# pull in sysconfig settings

NAME=app_manager
PIDFILE=/var/run/$NAME.pid
DAEMON=/usr/sbin/app_manager.py
DAEMON_INPUT_JSON="/etc/app_manager/config.json"
DAEMON_ARGS=" --json-config $DAEMON_INPUT_JSON" 
DAEMON_USER="root"

do_start() {
        # Return
        #   0 if daemon has been started
        #   1 if daemon was already running
        #   2 if daemon could not be started
	echo "Starting all applications using app_manager"

        if [ -f $PIDFILE ]; then
            echo "App Manager already running: see $PIDFILE. Current PID: $(cat $PIDFILE)" 
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
	echo "Stopping all applications using the app_manager"
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
                    0|1) echo -n "App Manager Daemon started successfully\n"  ;;
                    2) echo -n "Failed to start App Manager Daemon \n" ;;
                esac
		;;
	stop)
		do_stop
                case "$?" in
                    0|1) echo -n "App Manager Daemon stopped successfully\n"  ;;
                    2) echo -n "Failed to stop App Manager Daemon \n" ;;
                esac
		;;
	restart)
                echo "Restarting $DESC" "$NAME"
                do_stop
                case "$?" in
                    0|1)
                        echo -n "App Manager Daemon stopped successfully.\n"
			do_start
                        case "$?" in
                                0|1) echo "App Manager Daemon started successfully"  ;;
                                *) echo "Failed to start App Manager Daemon " ;; # Failed to start
                        esac
                       ;;
                    *)
                       # Failed to stop
                       echo "Failed to stop App Manager Daemon"
                       exit 1
                    ;;
                esac
                ;; 
	*)	
		echo "Usage: $0 {start|stop|restart}"
                ;;
esac
exit 0
