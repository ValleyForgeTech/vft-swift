#!/usr/bin/python

from __future__ import with_statement
import os 
import time
import boto.ec2

from fabric.api import *
from fabric.colors import green as _green, yellow as _yellow
from fabric.contrib import files
from fabric.utils import abort, error, puts, warn
from boto.exception import BotoServerError

## EC2 parameters
#my_ami = 'ami-0145d268' (older AMI that we will no longer use)
my_ami = 'ami-d8ae5db0'
my_keypair = 'swift_controller_test'
my_keydir = '.'
my_keyext = '.pem'
my_instancetype = 'm1.small'
my_security_group = 'vf_sec_grp'
my_ssh_port = '22'
my_cidr = '0.0.0.0/0'
my_login = 'ubuntu'
my_storagenode_count = 2
my_proxynode_count = 1
my_storagenode_dns = []
my_storagenode_ip = []
my_proxynode_dns = []
my_proxynode_ip = []


def build_swift_cluster():

    execute('setup_ec2_params')
    execute('create_ec2_proxynodes')
    execute('create_ec2_storagenodes')

    puts("Proxy Node IP Adresses:  %s".format(my_proxynode_ip))
    puts("Proxy Node Public DNS:  %s".format(my_proxynode_dns))

    puts("Storage Node IP Adresses:  %s".format(my_storagenode_ip))
    puts("Storage Node Public DNS:  %s".format(my_storagenode_dns))

    env.user  = my_login
    env.key_filename = my_keydir + '/' + my_keypair + my_keyext

    env.hosts = my_proxynode_dns
    execute('prep_nodes_install_software')
    env.hosts = my_storagenode_dns
    execute('prep_nodes_install_software')

    env.hosts = my_proxynode_dns
    execute('prep_proxynodes_phase_1')
    execute('prep_proxynodes_phase_2')
    env.hosts = my_storagenode_dns
    
    execute('prep_storagenodes_phase_1')

    puts('Waiting 90 seconds for storage nodes to reboot')
    time.sleep(90)

    execute('prep_storagenodes_phase_2')

def setup_ec2_params():
    """
    Creates the appropriate AWS key pair and security group.
    Authorizes the security group for SSH traffic over 22. 
    """

    puts('START: setup_ec2_params')

    my_ec2 = boto.ec2.connect_to_region("us-east-1")
    puts("Got EC2 Connection")

    # Get keypair by name. 
    # - Returns the key if it exists.
    # - Returns none otherwise.
    puts("Getting key pair by name '{}'".format(my_keypair))
    my_key = my_ec2.get_key_pair(my_keypair)

    # If key pair is none, create it.
    if my_key is None:
        puts("Key pair does not exist. Creating key pair, '{}'".format(my_keypair))
        my_key = my_ec2.create_key_pair(my_keypair)
        my_key.save(my_keydir)

    puts("Got key pair '{}'".format(my_keypair))

    # Get a list of all the security groups and use lambda to determine
    # if the group currently exists or not.
    #  - Reference: https://gist.github.com/steder/1498451
    security_groups = [g for g in my_ec2.get_all_security_groups() if g.name == my_security_group]
    group = security_groups[0] if security_groups else None

    # If the group does not exist, create it.
    if group is None:
        puts("Creating security group, '{}'".format(my_security_group))
        group = my_ec2.create_security_group(my_security_group, 'VF Tech Contoller Sec Group')

    puts("Got security group '{}'".format(group.name))

    # Attempt to authorize for swift traffic.
    # If the group is already authorized, we will get an InvalidPermission.Duplicate error, which is OK.
    authorize(group, 'tcp', 22, 22, my_cidr)     # SSH traffic
    authorize(group, 'tcp', 6000, 6002, my_cidr) # Swift server traffic
    authorize(group, 'tcp', 8080, 8080, my_cidr) # Web api traffic

    puts('END: setup_ec2_params')

def create_ec2_proxynodes():

    puts('START: create_ec2_proxynodes')

    my_ec2 = boto.ec2.connect_to_region("us-east-1")
    puts("Got EC2 Connection")

    ## Create storage nodes     
    reservation = my_ec2.run_instances(image_id=my_ami,key_name=my_keypair,placement='us-east-1b'
        ,instance_type=my_instancetype,security_groups=[my_security_group],min_count=my_proxynode_count,max_count=my_proxynode_count)
    
    puts("Created proxy nodes and waiting for them to spin up")
    
    puts('Started {} proxy nodes'.format(len(reservation.instances)))

    wait_for_instances(reservation.instances)

    puts('Reservation fulfilled. All proxy node instances started.')

    for instance in reservation.instances:
        # Store off DNS name of proxy node
        my_dns_name = instance.public_dns_name
        my_proxynode_dns.append(my_dns_name)

        # Store off private IP address of proxy node
        my_ip_address = instance.private_ip_address
        my_proxynode_ip.append(my_ip_address)

    puts('END: create_ec2_proxynodes')

def create_ec2_storagenodes():
    """
    Creates 'n' number of EC2 instances and attaches an EBS volume.
    """

    puts('START: create_ec2_instances')

    my_ec2 = boto.ec2.connect_to_region("us-east-1")
    puts("Got EC2 Connection")

    ## Create storage nodes     
    reservation = my_ec2.run_instances(image_id=my_ami,key_name=my_keypair,placement='us-east-1b'
        ,instance_type=my_instancetype,security_groups=[my_security_group],min_count=2,max_count=2)

    puts("Created storage nodes and waiting for them to spin up")

    puts('Started {} storage nodes'.format(len(reservation.instances)))

    wait_for_instances(reservation.instances)

    puts('Reservation fulfilled. All storage node instances started.')

    # Create and attach volumes to each node
    for instance in reservation.instances:
        puts('Setting up storage for instance {}'.format(instance.id))

        # Save off the DNS name
        my_dns_name = instance.public_dns_name
        my_storagenode_dns.append(my_dns_name)

        # Save off private IP address
        my_ip_address = instance.private_ip_address
        my_storagenode_ip.append(my_ip_address)

        # Tag each instance with 'storage_node'
        my_ec2.create_tags([instance.id], {"name": "storage_node"})

        puts('Creating volume for instance {}'.format(instance.id))

        # Create a storage volume
        volume = my_ec2.create_volume(size=10, zone='us-east-1b')

        puts('Created volume {}. Current status: {}'.format(volume.id, volume.status))

        while volume.status != 'available':
            puts('Waiting for volume to become available')

            # Sleep and update volume status
            time.sleep(2)

            # Update volume status
            volume.update()

            puts('Current volume status: {}'.format(volume.status))

        puts('Volume {} available'.format(volume.id))

        puts('Attaching volume {} to instance {} at /dev/xvdg'.format(volume.id, instance.id))

        # Attach the volume as 'sdg'
        attached_volume = my_ec2.attach_volume(volume.id, instance.id, '/dev/xvdg')

        puts('Successfully attached volume')

    puts('END: create_ec2_instances')

def prep_nodes_install_software():

    puts('START: prep_nodes_install_software')

    with settings(warn_only=True):
        
        sudo('apt-get update -y')
        #sudo('apt-get dist-upgrade -y')
        sudo ('apt-get install gcc bzr python-configobj python-coverage python-dev python-nose python-setuptools -y')
        sudo ('apt-get install python-simplejson python-xattr python-webob python-eventlet python-greenlet debhelper -y') 
        sudo ('apt-get install python-sphinx python-all python-openssl python-pastedeploy python-netifaces bzr-builddeb -y')
        sudo ('apt-get install xfsprogs memcached nmap git python-pip sqlite3 ssh curl -y')

        with cd ('/opt'):
            sudo ('git clone git://github.com/openstack/swift.git')

        with cd ('/opt/swift'):
            sudo ('python setup.py install')


    puts('END: prep_nodes_install_software')

def prep_storagenodes_phase_1():

    puts('START: prep_storagenodes_phase_1')

    with settings(warn_only=True):
    
        sudo ('mkdir -p /etc/swift')

        with cd ('/opt/swift/etc'):
            sudo ('cp account-server.conf-sample /etc/swift/account-server.conf')
            sudo ('cp container-server.conf-sample /etc/swift/container-server.conf')
            sudo ('cp object-server.conf-sample /etc/swift/object-server.conf')
            sudo ('cp proxy-server.conf-sample /etc/swift/proxy-server.conf')
            sudo ('cp drive-audit.conf-sample /etc/swift/drive-audit.conf')
            sudo ('cp swift.conf-sample /etc/swift/swift.conf')
        
        with cd ('/sys/block'):
            sudo ('ls -l | grep xvd')

        ## Prepare the attached disks
        sudo ('mkfs.xfs -f -i size=512 -L d1 /dev/xvdg')
        # sudo ('mkfs.xfs -f -i size=512 -L d2 /dev/xvdh')

        ## Mount the disks
        sudo ('mkdir -p /srv/node/d1')
        #sudo ('mkdir -p /srv/node/d2')
        sudo ('mount -t xfs -o noatime,nodiratime,logbufs=8 -L d1 /srv/node/d1')
        #sudo ('mount -t xfs -o noatime,nodiratime,logbufs=8 -L d2 /srv/node/d2')

        ## Create swift account and give ownership of /srv/node directory
        sudo ('useradd swift')
        sudo ('chown -R swift:swift /srv/node')

        ## Upload the following shell script
        put('./mount_devices', '/opt/swift/bin/mount_devices', mode=0755, use_sudo=True)
    
        ## Edit the following file
        files.append('/etc/init/start_swift.conf', 'start on runlevel [234]', use_sudo=True, partial=False, escape=True, shell=False)
        files.append('/etc/init/start_swift.conf', 'stop on runlevel [0156]', use_sudo=True, partial=False, escape=True, shell=False)
        files.append('/etc/init/start_swift.conf', 'exec /opt/swift/bin/mount_devices', use_sudo=True, partial=False, escape=True, shell=False)

        ## umount and reboot to make sure mount_devices script is executing
        sudo ('umount /srv/node/d1')
        #sudo ('umount /srv/node/d2')
        sudo ('reboot')

    puts('END: prep_storagenodes_phase_1')

def prep_proxynodes_phase_1():

    puts('START: prep_proxynodes_phase_1')

    with settings(warn_only=True):
    
        sudo ('mkdir -p /etc/swift')
        sudo ('useradd swift')

        with cd ('/opt/swift/etc'):
            sudo ('cp account-server.conf-sample /etc/swift/account-server.conf')
            sudo ('cp container-server.conf-sample /etc/swift/container-server.conf')
            sudo ('cp object-server.conf-sample /etc/swift/object-server.conf')
            sudo ('cp proxy-server.conf-sample /etc/swift/proxy-server.conf')
            sudo ('cp drive-audit.conf-sample /etc/swift/drive-audit.conf')
            sudo ('cp swift.conf-sample /etc/swift/swift.conf')

    puts('END: prep_proxynodes_phase_1')


def prep_proxynodes_phase_2():

    puts('START: prep_proxynodes_phase_2')

    with settings(warn_only=True):

        ## Create the following directory and give swift ownership
        sudo ('mkdir -p /var/cache/swift')
        sudo ('chown -R swift:swift /var/cache/swift')

        ## Add hash prefix and suffix
        files.sed ('/etc/swift/swift.conf', 'swift_hash_path_prefix = changeme', 'swift_hash_path_prefix =4f2b1586632d59a8', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        files.sed ('/etc/swift/swift.conf', 'swift_hash_path_suffix = changeme', 'swift_hash_path_suffix =4f2b1586632d59a8', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
 
        ## Tell swift where to log to events to
        files.append('/etc/rsyslog.d/0-swift.conf', 'local0.* /var/log/swift/all.log', use_sudo=True, partial=False, escape=True, shell=False)
        sudo ('mkdir -p /var/log/swift')
        sudo ('chown -R syslog.adm /var/log/swift')

        ## Create the ring files
        with cd ('/etc/swift'):
            sudo ('swift-ring-builder account.builder create 16 3 24')
            sudo ('swift-ring-builder container.builder create 16 3 24')
            sudo ('swift-ring-builder object.builder create 16 3 24')
            
        with cd ('/etc/swift'):
            for x in range(0, my_storagenode_count):
                sudo ('swift-ring-builder account.builder add z1-%s:6002/d1 10' % my_storagenode_ip[x])
                #sudo ('swift-ring-builder account.builder add z1-%s:6002/d2 10' % my_storagenode_ip[x])
                sudo ('swift-ring-builder container.builder add z1-%s:6001/d1 10' % my_storagenode_ip[x])
                #sudo ('swift-ring-builder container.builder add z1-%s:6001/d2 10' % my_storagenode_ip[x])
                sudo ('swift-ring-builder object.builder add z1-%s:6000/d1 10' % my_storagenode_ip[x])
                #sudo ('swift-ring-builder object.builder add z1-%s:6000/d2 10' % my_storagenode_ip[x])
        
        with cd ('/etc/swift'):
            sudo ('swift-ring-builder account.builder')
            sudo ('swift-ring-builder container.builder')
            sudo ('swift-ring-builder object.builder')

            sudo ('swift-ring-builder account.builder rebalance')
            sudo ('swift-ring-builder container.builder rebalance')
            sudo ('swift-ring-builder object.builder rebalance')
        
        # Pull down ring files to local directory
        get('/etc/swift/account.ring.gz', '.')
        get('/etc/swift/container.ring.gz', '.')
        get('/etc/swift/object.ring.gz', '.')   
        
        files.sed ('/etc/memcached.conf', '-l 127.0.0.1', '-l %s' % my_proxynode_ip[0], limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        sudo ('service memcached stop', pty=false)
        sudo ('service memcached start', pty=false)

        files.sed ('/etc/swift/proxy-server.conf', '# bind_ip = 0.0.0.0', 'bind_ip = %s' % my_proxynode_ip[0], limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        files.sed ('/etc/swift/proxy-server.conf', '# bind_port = 80', 'bind_port = 8080', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        files.sed ('/etc/swift/proxy-server.conf', '# memcache_servers = 127.0.0.1:11211', 'memcache_servers = %s:11211' % my_proxynode_ip[0], limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        files.sed ('/etc/swift/proxy-server.conf', '# allow_account_management = false', 'allow_account_management = true', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        files.sed ('/etc/swift/proxy-server.conf', '# account_autocreate = false', 'account_autocreate = true', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        sudo ('swift-init proxy start')

    puts('END: prep_proxynodes_phase_2')


def prep_storagenodes_phase_2():

    puts('START: prep_storagenodes_phase_2')

    with settings(warn_only=True):

        ## Make sure the drives are mounted after reboot
        run ('df -k')

        ## Create the following directory and give swift ownership
        sudo ('mkdir -p /var/cache/swift')
        sudo ('chown -R swift:swift /var/cache/swift')

        ## Add hash prefix and suffix
        files.sed ('/etc/swift/swift.conf', 'swift_hash_path_prefix = changeme', 'swift_hash_path_prefix =4f2b1586632d59a8', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        files.sed ('/etc/swift/swift.conf', 'swift_hash_path_suffix = changeme', 'swift_hash_path_suffix =4f2b1586632d59a8', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
 
        ## Tell swift where to log to events to
        files.append('/etc/rsyslog.d/0-swift.conf', 'local0.* /var/log/swift/all.log', use_sudo=True, partial=False, escape=True, shell=False)
        sudo ('mkdir -p /var/log/swift')
        sudo ('chown -R syslog.adm /var/log/swift')

        put ('./account.ring.gz', '/etc/swift/account.ring.gz', mode=0755, use_sudo=True)
        put ('./container.ring.gz', '/etc/swift/container.ring.gz', mode=0755, use_sudo=True)
        put ('./object.ring.gz', '/etc/swift/object.ring.gz', mode=0755, use_sudo=True)
        sudo ('chown -R swift:swift /etc/swift')

        files.sed ('/etc/default/rsync', 'RSYNC_ENABLE=false', 'RSYNC_ENABLE=true', limit='', use_sudo=True, backup='.bak', flags='', shell=False)
        
        put ('./rsyncd.conf', '/etc/rsyncd.conf', mode=0755, use_sudo=True)
        sudo ('service rsync start')
        sudo ('swift-init all start')

    puts('END: prep_storagenodes_phase_2')

def wait_for_instances(instances):
    """
    Waits for an array of instances to spin up.
    """

    ec2_initialized = False

    # Loop while we are still pending...
    while ec2_initialized is False:
        # Sleep 10 seconds to wait.
        puts('Waiting for instances to start...')
        time.sleep(2)

        # Logic used to determine if we are still 
        # waiting on one of the many VMs we started
        ec2_initialized = True

        for instance in instances:
            # Update instance status
            instance.update()

            if instance.state == 'pending':
                puts("Instance `{}` still warming up.  Current state: '{}'".format(instance.id, instance.state))
                
                # Set flag to false to force iterating through while loop again.
                ec2_initialized = False
            else:
                puts("Instance `{}` running!".format(instance.id))

def authorize(security_group,protocol,start_port,end_port,cidr):
    """
    Attempts to authorize a security group for traffic
    within a specific port range using the specified protocol.
    """

    try:
        puts("Authorizing group {} for {} traffic on ports {} <-> {} on CIDR {}".format(security_group.name, protocol, start_port, end_port, cidr))
        
        security_group.authorize(protocol,start_port,end_port,cidr)
        
    except BotoServerError, e:
        if e.code == 'InvalidPermission.Duplicate':
            # This is OK if the group already exists.  Log a warning and continue.
            warn("Group '{}' already for TCP traffic over port '{}'. Continuing".format(security_group.name, my_ssh_port, my_cidr))
        else:
            # Unexpected error.  Log and re-raise.
            error("Unexpected BotoServerError", exception=e)
            raise
