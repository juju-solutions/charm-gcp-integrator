import json
import os
import re
import subprocess
from base64 import b64decode
from math import ceil, floor
from time import sleep
from pathlib import Path

import yaml
import googleapiclient.discovery

from charmhelpers.core import hookenv
from charmhelpers.core.unitdata import kv

from charms.layer import status


ENTITY_PREFIX = 'charm.gcp'
MODEL_UUID = os.environ['JUJU_MODEL_UUID']
MAX_ROLE_NAME_LEN = 64
MAX_POLICY_NAME_LEN = 128
CREDS_FILE = Path('/root/.config/gcloud/application_default_credentials.json')
PROJECT = kv().get('charm.gcp.project')


def log(msg, *args):
    hookenv.log(msg.format(*args), hookenv.INFO)


def log_err(msg, *args):
    hookenv.log(msg.format(*args), hookenv.ERROR)


def get_credentials():
    """
    Get the credentials from either the config or the hook tool.

    Prefers the config so that it can be overridden.
    """
    no_creds_msg = 'missing credentials; set credentials config'
    config = hookenv.config()
    # try to use Juju's trust feature
    try:
        result = subprocess.run(['credential-get'],
                                check=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        creds = yaml.load(result.stdout.decode('utf8'))
        creds_data = creds['credential']['attributes']['file']
        update_credentials_file(creds_data)
        return True
    except FileNotFoundError:
        pass  # juju trust not available
    except subprocess.CalledProcessError as e:
        if 'permission denied' not in e.stderr.decode('utf8'):
            raise
        no_creds_msg = 'missing credentials access; grant with: juju trust'

    # try credentials config
    if config['credentials']:
        try:
            creds_data = b64decode(config['credentials']).decode('utf8')
            update_credentials_file(creds_data)
            return True
        except Exception:
            status.blocked('invalid value for credentials config')
            return False

    # no creds provided
    status.blocked(no_creds_msg)
    return False


def update_credentials_file(creds_data):
    """
    Write the credentials file.
    """
    CREDS_FILE.parent.mkdir(0o700, parents=True, exist_ok=True)
    with CREDS_FILE.open('w') as fp:
        os.fchmod(fp.fileno(), 0o600)
        fp.write(creds_data)
    creds = json.loads(creds_data)
    PROJECT = creds['project_id']
    kv().set('charm.gcp.project', PROJECT)


def label_instance(instance, zone, labels):
    """
    Label the given instance with the given labels.
    """
    log('Labelling instance {} in {} with: {}', instance, zone, labels)
    api = googleapiclient.discovery.build('compute', 'v1').instances()
    data = api.get(instance=instance, project=PROJECT, zone=zone)
    current_labels = data.get('labels', {})
    fingerprint = data['labelFingerprint']
    labels = dict(current_labels, **labels)
    api.setLabels(instance=instance, zone=zone, project=PROJECT, body={
        'labels': labels,
        'labelFingerprint': fingerprint,
    })


def enable_instance_inspection(application_name, instance, zone):
    """
    Enable instance inspection access for the given instance.
    """
    log('Enabling instance inspection for instance {} '
        'of application {} in zone {}',
        instance, application_name, zone)


def enable_network_management(application_name, instance, zone):
    """
    Enable network (firewall, subnet, etc.) management for the given
    instance.
    """
    log('Enabling network management for instance {} '
        'of application {} in zone {}',
        instance, application_name, zone)


def enable_load_balancer_management(application_name, instance, zone):
    """
    Enable load balancer (ELB) management for the given instance.
    """
    log('Enabling ELB for instance {} of application {} in zone {}',
        instance, application_name, zone)


def enable_block_storage_management(application_name, instance, zone):
    """
    Enable block storage (EBS) management for the given instance.
    """
    log('Enabling EBS for instance {} of application {} in zone {}',
        instance, application_name, zone)


def enable_dns_management(application_name, instance, zone):
    """
    Enable DNS (Route53) management for the given instance.
    """
    log('Enabling DNS (Route53) management for instance {} of '
        'application {} in zone {}',
        instance, application_name, zone)


def enable_object_storage_access(application_name, instance, zone,
                                 patterns):
    """
    Enable object storage (S3) read-only access for the given instance to
    resources matching the given patterns.
    """
    log('Enabling object storage (S3) read for instance {} of '
        'application {} in zone {}',
        instance, application_name, zone)


def enable_object_storage_management(application_name, instance, zone,
                                     patterns):
    """
    Enable object storage (S3) management for the given instance to
    resources matching the given patterns.
    """
    log('Enabling S3 write for instance {} of application {} in zone {}',
        instance, application_name, zone)


def cleanup(current_applications):
    """
    Cleanup unused IAM entities from the current model that are being managed
    by this charm instance.
    """
    # managed_entities = _get_managed_entities()
    # departed_applications = managed_entities.keys() - current_applications
    # if not departed_applications:
    #     return
    # log('Cleaning up unused GCP entities')
    # for app in departed_applications:
    #     entities = managed_entities.pop(app)
    #     for type? in entities['types?']:
    #         _cleanup_type?(type?)
    # _set_managed_entities(managed_entities)


# Internal helpers


class GCPError(Exception):
    """
    Exception class representing an error returned from the gcp-cli tool.

    Includes an `error_type` field to distinguish the different error cases.
    """
    @classmethod
    def get(cls, message):
        """
        Factory method to create either an instance of this class or a
        meta-subclass for certain `error_type`s.
        """
        error_type = None
        match = re.match(r'An error occurred \(([^)]+)\)', message)
        if match:
            error_type = match.group(1)
        for error_cls in (DoesNotExistGCPError, AlreadyExistsGCPError):
            if error_type in error_cls.error_types:
                return error_cls(error_type, message)
        return GCPError(error_type, message)

    def __init__(self, error_type, message):
        self.error_type = error_type
        self.message = message
        super().__init__(message)

    def __str__(self):
        return self.message


class DoesNotExistGCPError(GCPError):
    """
    Meta-error subclass of GCPError representing something not existing.
    """
    error_types = [
        'NoSuchEntity',
        'InvalidParameterValue',
    ]


class AlreadyExistsGCPError(GCPError):
    """
    Meta-error subclass of GCPError representing something already existing.
    """
    error_types = [
        'EntityAlreadyExists',
        'LimitExceeded',
        'IncorrectState',
    ]


def _elide(s, max_len):
    """
    Elide s in the middle to ensure it is under max_len.

    That is, shorten the string, inserting an ellipsis where the removed
    characters were to show that they've been removed.
    """
    if len(s) > max_len:
        hl = len(s - 3) / 2  # sub 3 for ellipsis
        headl, taill = floor(hl), ceil(hl)
        s = s[:headl] + '...' + s[-taill:]
    return s


def _get_managed_entities():
    """
    Get the set of IAM entities managed by this charm instance.
    """
    return kv().get('charm.gcp.managed-entities', {})


def _add_app_entity(app_name, entity_type, entity_name):
    """
    Add an IAM entity to the set managed by this charm instance.
    """
    managed_entities = _get_managed_entities()
    app_entities = managed_entities.setdefault(app_name, {
        'types?': [],
    })
    if entity_name not in app_entities[entity_type]:
        app_entities[entity_type].append(entity_name)
        _set_managed_entities(managed_entities)


def _set_managed_entities(managed_entities):
    """
    Update the cached set of IAM entities managed by this charm instance.
    """
    kv().set('charm.gcp.managed-entities', managed_entities)


def _retry_for_entity_delay(func):
    """
    Retry the given function a few times if it raises a DoesNotExistGCPError
    with an increasing delay.

    It sometimes takes GCP a bit for new entities to be available, so this
    helper retries an GCP call a few times allowing for any of the errors
    that indicate that an entity is not available, which may be a temporary
    state after adding it.
    """
    for attempt in range(4):
        try:
            func()
            break
        except DoesNotExistGCPError as e:
            log(e.message)
            if attempt == 3:
                raise GCPError(None, 'Timed out waiting for entity')
            delay = 10 * (attempt + 1)
            log('Retrying in {} seconds', delay)
            sleep(delay)
