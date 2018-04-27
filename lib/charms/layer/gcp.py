import json
import os
import re
import subprocess
from base64 import b64decode
from math import ceil, floor
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from charmhelpers.core import hookenv
from charmhelpers.core.unitdata import kv

from charms.layer import status


ENTITY_PREFIX = 'charm.gcp'
MODEL_UUID = os.environ['JUJU_MODEL_UUID']
MAX_ROLE_NAME_LEN = 64
MAX_POLICY_NAME_LEN = 128
CREDS_FILE = Path('/etc/juju-gcp-service-account.json')
PROJECT = kv().get('charm.gcp.project')

# When debugging hooks, for some reason HOME is set to /home/ubuntu, whereas
# during normal hook execution, it's /root. Set it here to be consistent.
os.environ['HOME'] = '/root'


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
    with CREDS_FILE.open('w') as fp:
        os.fchmod(fp.fileno(), 0o600)
        fp.write(creds_data)
    creds = json.loads(creds_data)
    PROJECT = creds['project_id']
    _gcloud('auth', 'activate-service-account', '--key-file', str(CREDS_FILE))
    kv().set('charm.gcp.project', PROJECT)


def create_account_key(model_uuid, application_name, relation_id):
    """
    Create a key on the service account for the given relation.
    """
    service_account = _get_service_account(model_uuid, application_name)
    with TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        tempdir.chmod(0o700)
        tempfile = tempdir / 'creds.json'
        stderr = _gcloud('iam', 'service-accounts', 'keys', 'create',
                         '--iam-account', service_account, str(tempfile),
                         return_stderr=True)
        # this sucks, and gcloud should return the key info in the stdout json
        match = re.match(r'created key \[([^\]]*)\]', stderr)
        if not match:
            raise GCPError(stderr)
        key_id = match.group(1)
        log('Created service account key {} for service account {}',
            key_id, service_account)
        creds = tempfile.read_text()
    kv().set('charm.gcp.account-keys.{}'.format(relation_id), {
        'service-account': service_account,
        'id': key_id,
    })
    return creds


def label_instance(instance, zone, labels):
    """
    Label the given instance with the given labels.
    """
    log('Labelling instance {} in {} with: {}', instance, zone, labels)
    _gcloud('compute', 'instances', 'add-labels', instance, '--zone', zone,
            '--labels', ','.join('='.join([k, v]) for k, v in labels.items()))


def enable_instance_inspection(model_uuid, application_name):
    """
    Enable instance inspection access for the given application.
    """
    log('Enabling instance inspection for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _add_roles(service_account, ['roles/compute.viewer'])


def enable_network_management(model_uuid, application_name):
    """
    Enable network management for the given application.
    """
    log('Enabling network management for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _add_roles(service_account, ['roles/compute.networkAdmin'])


def enable_security_management(model_uuid, application_name):
    """
    Enable security management for the given application.
    """
    log('Enabling security management for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _add_roles(service_account, ['roles/compute.securityAdmin'])


def enable_block_storage_management(model_uuid, application_name):
    """
    Enable block storage (disk) management for the given application.
    """
    log('Enabling block storage management for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _ensure_custom_role(name='compute.instanceStorageAdmin',
                        title='Storage admin for instances',
                        description='Attach and remove disks to instances',
                        permissions=['compute.instances.attachDisk',
                                     'compute.instances.detachDisk'])
    _add_roles(service_account, [
        'roles/compute.storageAdmin',
        'projects/{}/roles/compute.instanceStorageAdmin'.format(PROJECT),
    ])


def enable_dns_management(model_uuid, application_name):
    """
    Enable DNS management for the given application.
    """
    log('Enabling DNS management for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _add_roles(service_account, ['roles/dns.admin'])


def enable_object_storage_access(model_uuid, application_name):
    """
    Enable object storage read-only access for the given application.
    """
    log('Enabling object storage read for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _add_roles(service_account, ['roles/storage.objectViewer'])


def enable_object_storage_management(model_uuid, application_name):
    """
    Enable object storage management for the given application.
    """
    log('Enabling object store management for {}', application_name)
    service_account = _get_service_account(model_uuid, application_name)
    _add_roles(service_account, ['roles/storage.objectAdmin'])


def cleanup(relation_ids):
    """
    Cleanup unused account keys.
    """
    account_keys = kv().getrange('charm.gcp.account-keys.', strip=True)
    broken_relations = account_keys.keys() - relation_ids
    removed = []
    for relation_id in broken_relations:
        key = account_keys[relation_id]
        _gcloud('iam', 'service-accounts', 'keys', 'delete',
                '--iam-account', key['service-account'], key['id'])
        log('Deleted unused key {} for service account {}',
            key['id'], key['service-account'])
        removed.append(relation_id)
    # TODO: purge no-longer used SAs and clean up project policy
    kv().unsetrange(removed, prefix='charm.gcp.account-keys.')


# Internal helpers


class GCPError(Exception):
    """
    Exception class representing an error returned from the gcloud tool.
    """
    pass


def _elide(s, max_len, ellipsis='...'):
    """
    Elide s in the middle to ensure it is under max_len.

    That is, shorten the string, inserting an ellipsis where the removed
    characters were to show that they've been removed.
    """
    if len(s) > max_len:
        hl = (max_len - len(ellipsis)) / 2
        headl, taill = floor(hl), ceil(hl)
        s = s[:headl] + ellipsis + s[-taill:]
    return s


def _gcloud(cmd, subcmd, *args, return_stderr=False):
    """
    Call the gcloud tool.
    """
    cmd = ['gcloud', '--quiet', '--format=json', cmd, subcmd]
    cmd.extend(args)
    result = subprocess.run(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    stdout = result.stdout.decode('utf8').strip()
    stderr = result.stderr.decode('utf8').strip()
    if result.returncode != 0:
        raise GCPError(stderr)
    if return_stderr:
        # sometime gcloud is dumb about what it returns as the structured
        # output, forcing us to parse the unstructured stderr message
        return stderr
    if stdout:
        stdout = json.loads(stdout)
    return stdout


def _get_service_account(model_uuid, application_name):
    """
    Get or create the service account associated with the charm.
    """
    sa_cache_key = 'charm.gcp.service_accounts'
    app_name = _elide(application_name.lower(), 14, '--')
    sa_name = 'juju-gcp-{}-{}'.format(app_name, model_uuid[-6:])
    service_accounts = kv().get(sa_cache_key, {})
    if sa_name in service_accounts:
        return service_accounts[sa_name]

    cloud_service_accounts = _gcloud('iam', 'service-accounts', 'list')
    service_accounts.update({sa['email'].split('@')[0]: sa['email']
                             for sa in cloud_service_accounts})
    kv().set(sa_cache_key, service_accounts)
    if sa_name in service_accounts:
        return service_accounts[sa_name]

    sa = _gcloud('iam', 'service-accounts', 'create', sa_name)
    service_account = sa['email']
    service_accounts[sa_name] = service_account
    log('Created service account for {}: {}',
        application_name, service_account)
    kv().set(sa_cache_key, service_accounts)

    _add_roles(service_account, ['roles/iam.serviceAccountUser',
                                 'roles/iam.serviceAccountTokenCreator'])
    return service_account


def _ensure_custom_role(name, title, description, permissions):
    roles = {role['name'].split('/')[-1]
             for role in _gcloud('iam', 'roles', 'list', '--project', PROJECT)}
    if name in roles:
        return
    _gcloud('iam', 'roles', 'create', '--project', PROJECT,
            name, '--title', title, '--description', description,
            '--permissions', ','.join(permissions))
    log('Created custom role {}', name)


def _add_roles(service_account, roles):
    for role in roles:
        _gcloud('iam', 'projects', 'add-iam-policy-binding', PROJECT,
                '--member', 'serviceAccount:{}'.format(service_account),
                '--role', role)
        log('Added role {} to service account {}', role, service_account)
