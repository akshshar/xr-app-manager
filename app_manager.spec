Name: xr-app-manager 
Version: 0.1.0
Release: XR_6.3.1+
License: Copyright (c) 2019 Cisco Systems Inc. All rights reserved.
Packager: cisco
SOURCE0 : %{version}.tar.gz
Group: 3rd party application
Summary: XR App Manager compiled for WLR7 for IOS-XR 6.3.1+

%define install_user "ztp-user"

%description
This is the set of python and sysvinit scripts for xr-app-manager for WRL7: XR 6.3.1+

%prep

%setup -q -n src 

%install
mkdir -p %{buildroot}%{_sbindir}
install -m755 core/app_manager.py %{buildroot}%{_sbindir}
install -m755 ha_setup/exr_system_helper.py %{buildroot}%{_sbindir}

mkdir -p %{buildroot}/misc/app_host/scratch
cp -a ima_policy %{buildroot}/misc/app_host/scratch/ima_policy

mkdir -p %{buildroot}/etc/app_manager/
install -m644 config.json %{buildroot}/etc/app_manager

mkdir -p %{buildroot}/etc/rc.d/init.d
install -m755 sysvinit/app_manager.sh %{buildroot}/etc/rc.d/init.d/app_manager 

mkdir -p %{buildroot}/etc/logrotate.d
install -m644 logrotate/app_manager.conf %{buildroot}/etc/logrotate.d/app_manager.conf

mkdir -p %{buildroot}/misc/app_host/apps
cp -a apps/. %{buildroot}/misc/app_host/apps

%files

%defattr(-,root,root)
%{_sbindir}/app_manager.py
%{_sbindir}/exr_system_helper.py
/etc/app_manager/config.json
/etc/rc.d/init.d/app_manager
/etc/logrotate.d/app_manager.conf
/misc/app_host/apps
/misc/app_host/scratch/ima_policy 

%post

# Mutiple files can be specified for scp to standby
%{_sbindir}/exr_system_helper.py --file /etc/rc.d/init.d/app_manager --file %{_sbindir}/app_manager.py --file /etc/logrotate.d/app_manager.conf --user %{install_user}

# Add app_manager service to chkconfig to run on reloads of either RP
chkconfig --add app_manager
# exr_system_helper.py can be used to run bash commands on standby RP XR LXC. Use this to create directories before trying to copy them over scp.
# Remember, bash commands are always executed at the end by exr_system_helper.py. So decouple bash commands that are a prerequisite for any scp operation
%{_sbindir}/exr_system_helper.py --cmd "chkconfig --add app_manager" --user %{install_user}

# exr_system_helper.py can be used to run bash commands on standby. Use this to create directories before trying to copy them over scp
%{_sbindir}/exr_system_helper.py --cmd "mkdir -p /etc/app_manager" --user %{install_user}
%{_sbindir}/exr_system_helper.py --directory /etc/app_manager/ --user %{install_user}


# Sync artifacts and config files for apps to standby
%{_sbindir}/exr_system_helper.py --cmd "mkdir -p /misc/app_host/apps" --user %{install_user}
%{_sbindir}/exr_system_helper.py --directory /misc/app_host/apps --user %{install_user}

# Run master installation script for all apps under /misc/app_host/apps on active and stanbdy
/misc/app_host/apps/install_all_apps.sh
%{_sbindir}/exr_system_helper.py --cmd "/misc/app_host/apps/install_all_apps.sh" --user %{install_user}


# Finally start the app_manager on active RP and on Standby RP (if present)
service app_manager restart
%{_sbindir}/exr_system_helper.py --cmd "service app_manager restart" --user %{install_user}


# Fix ima_policy on Standby and Active host layers.
%{_sbindir}/exr_system_helper.py --file /misc/app_host/scratch/ima_policy --user %{install_user}
%{_sbindir}/exr_system_helper.py -i "cp /misc/app_host/scratch/ima_policy /etc/ima_policy" -j "cp /misc/app_host/scratch/ima_policy /etc/ima_policy" --user %{install_user}
