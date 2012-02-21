from eutester import Eutester
from eucaops_api import Eucaops_api
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
import time
import re
import sys
import pprint
import boto
from boto.ec2.image import Image
from boto.ec2.instance import Reservation
from boto.ec2.volume import Volume

class Eucaops(Eutester,Eucaops_api):
    
    def __init__(self, config_file=None, hostname=None, password=None, keypath=None, credpath=None, aws_access_key_id=None, aws_secret_access_key = None,account="eucalyptus",user="admin", boto_debug=0):
        super(Eucaops, self).__init__(config_file, hostname, password, keypath, credpath, aws_access_key_id, aws_secret_access_key,account, user, boto_debug)
        self.poll_count = 24
        self.test_resources = {}
        self.test_resources["keys"] = []
        self.test_resources["buckets"] = []
        self.test_resources["reservations"] = []
        self.test_resources["volumes"] = []
        self.test_resources["snapshots"] = []
        self.test_resources["keypairs"] = []
        self.test_resources["security-groups"] = []
        self.test_resources["images"] = []
        
    def create_bucket(self,bucket_name):
        """
        Create a bucket.  If the bucket already exists and you have
        access to it, no error will be returned by AWS.
        Note that bucket names are global to S3
        so you need to choose a unique name.
        """
        # First let's see if we already have a bucket of this name.
        # The lookup method will return a Bucket object if the
        # bucket exists and we have access to it or None.
        bucket = self.get_bucket_by_name(bucket_name)
        if bucket:
            self.debug( 'Bucket (%s) already exists' % bucket_name )
        else:
                # Let's try to create the bucket.  This will fail if
                # the bucket has already been created by someone else.
            try:
                bucket = self.walrus.create_bucket(bucket_name)
            except self.walrus.provider.storage_create_error, e:
                self.debug( 'Bucket (%s) is owned by another user' % bucket_name )
                return None
            if not self.get_bucket_by_name(bucket.name):
                self.fail("Bucket could not be found after creation")
                return None
        self.test_resources["buckets"].append(bucket)
        return bucket
    
    def delete_bucket(self, bucket):
        """
        Delete a bucket.
        bucket_name  The name of the Walrus Bucket
        """
        # First let's see if we already have a bucket of this name.
        # The lookup method will return a Bucket object if the
        # bucket exists and we have access to it or None.
        bucket_name = bucket.name
        try:
            bucket.delete()
        except self.walrus.provider.storage_create_error, e:
                self.debug( 'Bucket (%s) is owned by another user' % bucket_name )
                return None
            
        ### Check if the bucket still exists
        if self.get_bucket_by_name(bucket_name):
            self.fail("Bucket still exists after delete operation")
        
    
    def get_bucket_by_name(self, bucket_name):
        """
        Lookup a bucket by name, if it does not exist return false
        """
        bucket = self.walrus.lookup(bucket_name)
        if bucket:
            return bucket
        else:
            return False
    
    def upload_object_file(self, bucket_name, key_name, path_to_file):
        """
        Write the contents of a local file to walrus
        bucket_name   The name of the walrus Bucket.
        key_name      The name of the object containing the data in walrus.
        path_to_file  Fully qualified path to local file.
        """
        bucket = self.get_bucket_by_name(bucket_name)
        if bucket == None:
            self.fail("Could not find bucket " + bucket_name + " to upload file")
            return
        # Get a new, blank Key object from the bucket.  This Key object only
        # exists locally until we actually store data in it.
        key = bucket.new_key(key_name)
        if key == None:
            self.fail( "Unable to create key " + key_name  )
        key.set_contents_from_filename(path_to_file)
        self.test_resources["keys"].append(key)
        return key
    
    def get_objects_by_prefix(self, bucket_name, prefix):
        """
        Get keys in the specified bucket that match the prefix if no prefix is passed all objects are returned
        as a result set.
        If only 1 key matches it will be returned as a Key object. 
        """
        bucket = self.get_bucket_by_name(bucket_name)
        keys = bucket.get_all_keys(prefix=prefix)
        if len(keys) <= 1:
            self.fail("Unable to find any keys with prefix " + prefix + " in " + bucket )
        if len(keys) == 2:
            return keys[0]
        return keys
        
    def delete_object(self, object):
        bucket = object.bucket
        name = object.name
        object.delete()
        try:
            self.walrus.get_bucket(bucket).get_key(name)
            self.fail("Walrus bucket still exists after delete")
        except Excetption, e:
            return
        
    
    def add_keypair(self,key_name=None):
        """
        Add a keypair with name key_name unless it already exists
        key_name      The name of the keypair to add and download.
        """
        if key_name==None:
            key_name = "keypair-" + str(int(time.time())) 
        self.debug(  "Looking up keypair " + key_name )
        key = self.ec2.get_all_key_pairs(keynames=[key_name])    
        if key == []:
            self.debug( 'Creating keypair: %s' % key_name)
            # Create an SSH key to use when logging into instances.
            key = self.ec2.create_key_pair(key_name)
            # AWS will store the public key but the private key is
            # generated and returned and needs to be stored locally.
            # The save method will also chmod the file to protect
            # your private key.
            key.save(self.key_dir)
            self.test_resources["keypairs"].append(key)
            return key
        else:
            self.debug(  "Key " + key_name + " already exists")
    
    def delete_keypair(self,keypair):
        """
        Delete the keypair object passed in and check that it no longer shows up
        keypair      Keypair object to delete and check
        """
        name = keypair.name
        self.debug(  "Sending delete for keypair: " + name)
        keypair.delete()
        keypair = self.ec2.get_all_key_pairs(keynames=[name])
        if len(keypair) > 0:
            self.fail("Keypair found after attempt to delete it")
        return
    
    def add_group(self, group_name=None, fail_if_exists=False ):
        """
        Add a security group to the system with name group_name, if it exists dont create it
        group_name      Name of the security group to create
        fail_if_exists  IF set, will fail if group already exists, otherwise will return the existing group
        returns boto group object upon success or None for failure
        """
        group=None
        if group_name == None:
            group_name = "group-" + str(int(time.time()))
        if self.check_group(group_name):
            if ( fail_if_exists == True ):
                self.fail(  "Group " + group_name + " already exists")
            else:
                self.debug(  "Group " + group_name + " already exists")
                group = self.ec2.get_all_security_groups(group_name)[0]
            self.test_resources["security-groups"].append(group)
            return group
        else:
            self.debug( 'Creating Security Group: %s' % group_name)
            # Create a security group to control access to instance via SSH.
            group = self.ec2.create_security_group(group_name, group_name)
        return group
    
    def delete_group(self, group):
        """
        Delete the group object passed in and check that it no longer shows up
        group      Group object to delete and check
        """
        name = group.name
        self.debug( "Sending delete for group: " + name )
        group.delete()
        if self.check_group(name):
            self.fail("Group found after attempt to delete it")
        return
    
    def check_group(self, group_name):
        """
        Check if a group with group_name exists in the system
        group_name      Group name to check for existence
        """
        self.debug( "Looking up group " + group_name )
        group = self.ec2.get_all_security_groups(groupnames=[group_name])
        if group == []:
            return False
        else:
            return True
    
    def authorize_group_by_name(self,group_name="default", port=22, protocol="tcp", cidr_ip="0.0.0.0/0"):
        """
        Authorize the group with group_name, 
        group_name      Name of the group to authorize, default="default"
        port            Port to open, default=22
        protocol        Protocol to authorize, default=tcp
        cidr_ip         CIDR subnet to authorize, default="0.0.0.0/0" everything
        """
        try:
            self.debug( "Attempting authorization of group" )
            self.ec2.authorize_security_group_deprecated(group_name,ip_protocol=protocol, from_port=port, to_port=port, cidr_ip=cidr_ip)
        except self.ec2.ResponseError, e:
            if e.code == 'InvalidPermission.Duplicate':
                self.debug( 'Security Group: %s already authorized' % group_name )
            else:
                raise
            
    def authorize_group(self,group, port=22, protocol="tcp", cidr_ip="0.0.0.0/0"):
        """
        Authorize the group with group_name, 
        group_name      Name of the group to authorize, default="default"
        port            Port to open, default=22
        protocol        Protocol to authorize, default=tcp
        cidr_ip         CIDR subnet to authorize, default="0.0.0.0/0" everything
        """
        group_name = group.name
        try:
            self.debug( "Attempting authorization of group" )
            self.ec2.authorize_security_group_deprecated(group_name,ip_protocol=protocol, from_port=port, to_port=port, cidr_ip=cidr_ip)
        except self.ec2.ResponseError, e:
            if e.code == 'InvalidPermission.Duplicate':
                self.debug( 'Security Group: %s already authorized' % group_name )
            else:
                raise
    
    def wait_for_instance(self,instance, state="running"):
        """
        Wait for the instance to enter the state
        instance      Boto instance object to check the state on
        state        state that we are looking for
        """
        poll_count = self.poll_count
        self.debug( "Beginning poll loop for instance " + str(instance) + " to go to " + state )
        instance.update()
        instance_original_state = instance.state
        start = time.time()
        elapsed = 0
        ### If the instance changes state or goes to the desired state before my poll count is complete
        while( poll_count > 0) and (instance.state != state):
            poll_count -= 1
            time.sleep(10)
            instance.update()
            elapsed = (time.time()- start)
            if (instance.state != instance_original_state):
                break
        self.debug("Instance("+instance.id+") State("+instance.state+") Poll("+str(self.poll_count-poll_count)+") time elapsed (" +str(elapsed).split('.')[0]+")")
        #self.debug( "Waited a total o" + str( (self.poll_count - poll_count) * 10 ) + " seconds" )
        if instance.state != state:
                self.fail(str(instance) + " did not enter the proper state and was left in " + instance.state)
        self.debug( str(instance) + ' is now in ' + instance.state )

    def wait_for_reservation(self,reservation, state="running"):
        """
        Wait for the an entire reservation to enter the state
        reservation  Boto reservation object to check the state on
        state        state that we are looking for
        """
        self.debug( "Beginning poll loop for the " + str(len(reservation.instances))   + " found in " + str(reservation) )
        for instance in reservation.instances:
            self.wait_for_instance(instance, state)
    
    def create_volume(self, azone, size=1, snapshot=None):
        """
        Create a new EBS volume then wait for it to go to available state, size or snapshot is mandatory
        azone        Availability zone to create the volume in
        size         Size of the volume to be created
        snapshot     Snapshot to create the volume from
        """
        # Determine the Availability Zone of the instance
        poll_count = self.poll_count
        poll_interval = 10
        self.debug( "Sending create volume request" )
        volume = self.ec2.create_volume(size, azone)
        # Wait for the volume to be created.
        self.debug( "Polling for volume to become available")
        while volume.status != 'available' and (poll_count > 0):
            poll_count -= 1
            time.sleep(poll_interval)
            volume.update()
            self.debug( str(volume) + " in " + volume.status +" state")   
        if poll_count == 0:
            self.fail(str(volume) + " never went to available and stayed in " + volume.status)
            self.debug( "Deleting volume that never became available")
            volume.delete()
            return None
        self.debug( "Done. Waited a total of " + str( (self.poll_count - poll_count) * poll_interval) + " seconds" )
        self.test_resources["volumes"].append(volume)
        return volume
    
    def delete_volume(self, volume):
        """
        Delete the EBS volume then check that it no longer exists
        volume        Volume object to delete
        """
        self.ec2.delete_volume(volume.id)
        self.debug( "Sent delete for volume: " +  volume.id  )
        poll_count = 10
        volume.update()
        while ( volume.status != "deleted") and (poll_count > 0):
            poll_count -= 1
            volume.update()
            self.debug( str(volume) + " in " + volume.status )
            self.sleep(10)

        if poll_count == 0:
            self.fail(str(volume) + " left in " +  volume.status)
            return volume
    
    def delete_all_volumes(self):
        volumes = self.ec2.get_all_volumes()
        for volume in volumes:
            self.delete_volume(volume.id)
    
    def detach_volume(self, volume):
        if volume == None:
            self.fail("Volume does not exist")
            return volume
        volume.detach()
        volume.update()
        self.debug( "Sent detach for volume: " + volume.id + " which is currently in state: " + volume.status)
        poll_count = 10 
        while ( volume.status == "in-use") and (poll_count > 0):
            poll_count -= 1
            self.debug( str(volume) + " in " + volume.status)
            self.sleep(10)
            volume.update()
        self.debug(str(volume) + " left in " +  volume.status)
        if poll_count == 0:
            self.fail(str(volume) + " left in " +  volume.status)
        return volume
    
    def create_snapshot(self, volume_id, description="", waitOnProgress=0, poll_interval=10, timeout=0):
        """
        Create a new EBS snapshot from an existing volume then wait for it to go to the created state. By default will poll for poll_count.
        If waitOnProgress is specified than will wait on "waitOnProgress" # of periods w/o progress before failing
        An overall timeout can be given for both methods, by default the timeout is not used.    
        volume_id        (mandatory string) Volume id of the volume to create snapshot from
        description      (optional string) string used to describe the snapshot
        waitOnProgress   (optional integer) # of poll intervals to wait while 0 progress is made before exiting, overrides "poll_count" when used
        poll_interval    (optional integer) time to sleep between polling snapshot status
        timeout          (optional integer) over all time to wait before exiting as failure
        returns snapshot 
        """
        if (waitOnProgress > 0 ):
            poll_count = waitOnProgress
        else:
            poll_count = self.poll_count
        curr_progress = 0 
        last_progress = 0
        elapsed = 0
        polls = 0
        snap_start = time.time()
        #self.debug("Sending create snapshot request for volume:"+volume_id)
        snapshot = self.ec2.create_snapshot( volume_id )
        self.debug("Waiting for snapshot (" + snapshot.id + ") creation to complete")
        while ( (poll_count > 0) and ((timeout == 0) or (elapsed <= timeout)) ):
            time.sleep(poll_interval)
            polls += 1
            snapshot.update()
            curr_progress = int(snapshot.progress.replace('%',''))
            #if progress was made, then reset timer 
            if ((waitOnProgress > 0) and (curr_progress > last_progress)):
                poll_count = waitOnProgress
            else: 
                poll_count -= 1
            elapsed = int(time.time()-snap_start)
            self.debug("Snapshot:"+snapshot.id+" Status:"+snapshot.status+" Progress:"+snapshot.progress+" Polls:"+str(polls)+" Time Elapsed:"+str(elapsed))    
            if (snapshot.status == 'completed'):
                self.debug("Snapshot created after " + str(elapsed) + " seconds. " + str(polls) + " X ("+str(poll_interval)+" second) polling invervals. Status:"+snapshot.status+", Progress:"+snapshot.progress)
                self.test_resources["snapshots"].append(snapshot)
                return snapshot
        #At least one of our timers has been exceeded, fail and exit 
        self.fail(str(snapshot) + " failed after Polling("+str(polls)+") ,Waited("+str(elapsed)+" sec), last reported (status:" + snapshot.status+" progress:"+snapshot.progress+")")
        self.debug("Deleting snapshot("+snapshot.id+"), never progressed to 'created' state")
        snapshot.delete()
        return None
        
    
    def delete_snapshot(self,snapshot):
        snapshot.delete()
        self.debug( "Sent snapshot delete request for snapshot: " + snapshot.id)
        poll_count = 5
        while ( len(self.ec2.get_all_snapshots(snapshot_ids=[snapshot.id])) > 0) and (poll_count > 0):
            poll_count -= 1
            self.sleep(10)
        if poll_count == 0:
            self.fail(str(snapshot) + " left in " +  snapshot.status + " with " + str(snapshot.progress) + "% progress")
        return snapshot
    
    def register_snapshot( self, snap_id, rdn="/dev/sda1", description="bfebs", windows=False, bdmdev=None, name=None, ramdisk=None, kernel=None, dot=True ):
        '''
        Register an image snapshot
        snap_id        (mandatory string) snapshot id
        name           (mandatory string) name of image to be registered
        description    (optional string) description of image to be registered
        bdmdev         (optional string) block-device-mapping device for image
        rdn            (optional string) root-device-name for image
        dot            (optional boolean) Delete On Terminate boolean
        windows        (optional boolean) Is windows image boolean
        kernel         (optional string) kernal (note for windows this name should be "windows"
        '''
        
        if (bdmdev is None):
            bdmdev=rdn
        if (name is None):
            name="bfebs_"+snap_id
        if ( windows is True ) and ( kernel is not None):
            kernel="windows"     
            
        bdmap = BlockDeviceMapping()
        block_dev_type = BlockDeviceType()
        block_dev_type.snapshot_id = snap_id
        block_dev_type.delete_on_termination = dot
        bdmap[bdmdev] = block_dev_type
            
        self.debug("Register image with: snap_id:"+str(snap_id)+", rdn:"+str(rdn)+", desc:"+str(description)+", windows:"+str(windows)+", bdname:"+str(bdmdev)+", name:"+str(name)+", ramdisk:"+str(ramdisk)+", kernel:"+str(kernel))
        image_id = self.ec2.register_image(name=name, description=description, kernel_id=kernel, ramdisk_id=ramdisk, block_device_map=bdmap, root_device_name=rdn)
        return image_id
        
    def register_image( self, snap_id, rdn=None, description=None, image_location=None, windows=False, bdmdev=None, name=None, ramdisk=None, kernel=None ):
        '''
        Register an image snapshot
        snap_id        (optional string) snapshot id
        name           (optional string) name of image to be registered
        description    (optional string) description of image to be registered
        bdm            (optional block_device_mapping) block-device-mapping object for image
        rdn            (optional string) root-device-name for image
        kernel         (optional string) kernal (note for windows this name should be "windows"
        image_location (optional string) path to s3 stored manifest 
        '''

        image_id = self.ec2.register_image(name=name, description=description, kernel_id=kernel, image_location=image_location, ramdisk_id=ramdisk, block_device_map=bdmdev, root_device_name=rdn)
        self.test_resources["images"].append(image_id)
        return image_id
    
    def get_emi(self, emi="emi-", root_device_type=None, root_device_name=None, location=None, state="available", arch=None, owner_id=None):
        """
        Get an emi with name emi, or just grab any emi in the system. Additional 'optional' match criteria can be defined.
        emi              (mandatory) Partial ID of the emi to return, defaults to the 'emi-" prefix to grab any
        root_device_type (optional string)  example: 'instance-store' or 'ebs'
        root_device_name (optional string)  example: '/dev/sdb' 
        location         (optional string)  partial on location match example: 'centos'
        state            (optional string)  example: 'available'
        arch             (optional string)  example: 'x86_64'
        owner_id         (optional string) owners numeric id
        """
        
        images = self.ec2.get_all_images()
        for image in images:
            
            if not re.match(emi, image.id):      
                continue  
            if ((root_device_type is not None) and (image.root_device_type != root_device_type)):
                continue            
            if ((root_device_name is not None) and (image.root_device_name != root_device_name)):
                continue       
            if ((state is not None) and (image.state != state)):
                continue            
            if ((location is not None) and (not re.match( location, image.location))):
                continue           
            if ((arch is not None) and (image.architecture != arch)):
                continue                
            if ((owner_id is not None) and (image.owner_id != owner_id)):
                continue
            
            return image
        raise Exception("Unable to find an EMI")
        return None
    
    
    
    def get_volume(self, volume_id="vol-", status=None, attached_instance=None, attached_dev=None, snapid=None, zone=None, minsize=1, maxsize=None):
        '''
        Return first volume that matches the criteria. Criteria options to be matched:
        volume_id         (optional string) string present within volume id
        status            (optional string) examples: 'in-use', 'creating', 'available'
        attached_instance (optional string) instance id example 'i-1234abcd'
        attached_dev      (optional string) example '/dev/sdf'
        snapid            (optional string) snapshot volume was created from example 'snap-1234abcd'
        zone              (optional string) zone of volume example 'PARTI00'
        minsize           (optional integer) minimum size of volume to be matched
        maxsize           (optional integer) maximum size of volume to be matched
        '''
        if (attached_instance is not None) or (attached_dev is not None):
            status='in-use'
    
        volumes = self.ec2.get_all_volumes()
        for volume in volumes:
            if not re.match(volume_id, volume.id):
                continue
            if (snapid is not None) and (volume.snapshot_id != snapid):
                continue
            if (zone is not None) and (volume.zone != zone):
                continue
            if (status is not None):
                if (volume.status != status):
                    continue
                else:
                    if (attached_instance is not None) and ( volume.attach_data.instance_id != attached_instance):
                        continue
                    if (attached_dev is not None) and (volume.attach_data.device != attached_dev):
                        continue
            if not (volume.size >= minsize) and ((maxsize is None) or (volume.size <= maxsize)):
                continue
            return volume
        raise Exception("Unable to find matching volume")
        return None


    def run_instance(self, image=None, keypair=None, group="default", type=None, zone=None, min=1, max=1):
        """
        Run instance/s and wait for them to go to the running state
        image      Image object to use, default is pick the first emi found in the system
        keypair    Keypair name to use for the instances, defaults to none
        group      Security group name to apply to this set of instnaces, defaults to none
        type       VM type to use for these instances, defaults to m1.small
        zone       Availability zone to run these instances
        min        Minimum instnaces to launch, default 1
        max        Maxiumum instances to launch, default 1
        """
        if image == None:
            images = self.ec2.get_all_images()
            for emi in images:
                if re.match("emi",emi.name):
                    image = emi         
        self.debug( "Attempting to run image " + str(image) + " in group " + group)
        reservation = image.run(key_name=keypair,security_groups=[group],instance_type=type, placement=zone, min_count=min, max_count=max)
        self.wait_for_reservation(reservation)
        for instance in reservation.instances:
            if instance.state != "running":
                self.fail("Instance " + instance.id + " now in " + instance.state  + " state")
            else:
                self.debug( "Instance " + instance.id + " now in " + instance.state  + " state")
        self.test_resources["reservations"].append(reservation)
        return reservation
    
    def get_available_vms(self, type=None, zone=None):
        """
        Get available VMs of a certain type or return a dictionary with all types and their available vms
        type        VM type to get available vms 
        """
        
        zones = self.ec2.get_all_zones('verbose') 
        if type == None:
            type = "m1.small"
        ### Look for the right place to start parsing the zones
        zone_index = 0
        if zone != None: 
            while zone_index < len(zones):
                current_zone = zones[zone_index]
                if re.search( zone, current_zone.name):
                    break
                zone_index += 7
            if zone_index > (len(zones) - 1)   :
                self.fail("Was not able to find AZ: " + zone)
                raise Exception("Unable to find Availability Zone")    
        else:
            zone = zones[0].name
            
        ### Inline switch statement
        type_index = {
                      'm1.small': 2,
                      'c1.medium': 3,
                      'm1.large': 4,
                      'm1.xlarge': 5,
                      'c1.xlarge': 6,
                      }[type] 
        type_state = zones[ zone_index + type_index ].state.split()
        self.debug("Finding available VMs: Partition=" + zone +" Type= " + type + " Number=" +  str(int(type_state[0])) )
        return int(type_state[0])
    
    def release_address(self, ip=None):
        """
        Release all addresses or a particular IP
        ip        IP to release
        """   
        if ip==None:
            ## Clear out all addresses found
            self.debug( "Releasing all used addresses")
            address_output = self.sys("euca-describe-addresses")
            addresses = self.grep("ADDRESS",address_output)
            total_addresses = len(addresses)
            for address in addresses:
                if re.search("nobody", address) == None:
                    self.sys("euca-release-address " + address.split()[1] )
            address_output = self.sys("euca-describe-addresses")
            free_addresses = self.grep("nobody", address_output)
            if len(free_addresses) < total_addresses:
                self.debug( "Some addresses still in use after attempting to release")
                #self.fail("Some addresses still in use after attempting to release")
        else:
            self.debug( "Releasing address " + ip )
            self.sys("euca-release-address " + ip )
            address_output = self.sys("euca-describe-addresses")
            free_addresses = self.grep( ip + ".*nobody", address_output)
            if len(free_addresses) < 1:
                self.debug( "Some addresses still in use after attempting to release" )
                #self.fail("Address still in use after attempting to release")
            
    def terminate_instances(self, reservation=None):
        """
        Terminate instances in the system
        reservation        Reservation object to terminate all instances in, default is to terminate all instances
        """
        ### If a reservation is not passed then kill all instances
        if reservation==None:
#            reservations.stop_all()
            reservations = self.ec2.get_all_instances()
            for res in reservations:
                for instance in res.instances:
                    self.debug( "Sending terminate for " + str(instance) )
                    instance.terminate()
                self.wait_for_reservation(res, state="terminated")
        ### Otherwise just kill this reservation
        else:
            for instance in reservation.instances:
                    self.debug( "Sending terminate for " + str(instance) )
                    instance.terminate()
            self.wait_for_reservation(reservation, state="terminated")
            
    def modify_property(self, property, value):
        """
        Modify a eucalyptus property through the command line euca-modify-property tool
        property        Property to modify
        value           Value to set it too
        """
        command = self.eucapath + "/usr/sbin/euca-modify-property -p " + property + "=" + value
        if self.found(command, property):
            self.test_name("Properly modified property")
        else:
            self.fail("Could not modify " + property)
    
    def get_master(self, component="clc"):
        """
        Find the master of any type of component and return its IP, by default returns the master CLC
        component        Component to find the master, possible values ["clc", "sc", "cc", "ws"]
        """
        service = "eucalyptus"
        if component == "sc":
            service = "storage"
        if component == "ws":
            service = "walrus"
        if component == "cc":
            service = "cluster"
        self.debug( "Looking for enabled " + component )        
        ### GO through both clcs and check which ip it thinks is enabled for this service type
        services = self.sys( self.eucapath + "/usr/sbin/euca-describe-services")
        master = ""
        try:
            line = self.grep("SERVICE\s+" + service + ".*ENABLED", services)[0]
            service_url = line.split()[6]
            master = service_url.split(":")[1].strip("/")
            self.swap_ssh(master)
            return master
        except Exception, e:
            self.fail("Unable to find redundant components")
            self.fail(str(e))
            raise
    
    def cleanup_artifacts(self):
        self.debug("Starting cleanup of artifacts")
        for key,array in self.test_resources.iteritems():
            for item in array:
                try:
                    ### SWITCH statement for particulars of removing a certain type of resources
                    if isinstance(item, Image):
                        item.deregister()
                    elif isinstance(item, Reservation):
                        self.terminate_instances(item)
                    elif isinstance(item, Volume):
                        try:
                            self.detach_volume(item)
                        except:
                            pass
                        self.delete_volume(item)
                    else:
                        item.delete()
                except Exception, e:
                    self.fail("Unable to delete item: " + str(item) + "\n" + str(e))
                    
    def get_current_resources(self,verbose=False):
        '''Return a dictionary with all known resources the system has. Optional pass the verbose=True flag to print this info to the logs
           Included resources are: addresses, images, instances, key_pairs, security_groups, snapshots, volumes, zones
        
        '''
        current_artifacts = {}
        current_artifacts["addresses"] = self.ec2.get_all_addresses()
        current_artifacts["images"] = self.ec2.get_all_images()
        current_artifacts["instances"] = self.ec2.get_all_instances()
        current_artifacts["key_pairs"] = self.ec2.get_all_key_pairs()
        current_artifacts["security_groups"] = self.ec2.get_all_security_groups()
        current_artifacts["snapshots"] = self.ec2.get_all_snapshots()
        current_artifacts["volumes"] = self.ec2.get_all_volumes()
        current_artifacts["zones"] = self.ec2.get_all_zones()
        
        if verbose:
            self.info("Current resources in the system:\n" + pprint.pformat(current_artifacts))
        return current_artifacts
        
            
       
        
        
        
        

