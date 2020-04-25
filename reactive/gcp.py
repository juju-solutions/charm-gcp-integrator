import subprocess
from traceback import format_exc

from charms.reactive import (
    when_all,
    when_any,
    when_not,
    toggle_flag,
    clear_flag,
    hook,
)
from charms.reactive.relations import endpoint_from_name
from charmhelpers.core import hookenv

from charms import layer


@when_all('snap.installed.google-cloud-sdk')
def set_app_ver():
    try:
        result = subprocess.run(['snap', 'info', 'google-cloud-sdk'],
                                stdout=subprocess.PIPE)
    except subprocess.CalledProcessError:
        pass
    else:
        stdout = result.stdout.decode('utf8').splitlines()
        version = [line.split()[1] for line in stdout if 'installed' in line]
        if version:
            hookenv.application_version_set(version[0])


@when_any('config.changed.credentials')
def update_creds():
    clear_flag('charm.gcp.creds.set')


@when_not('charm.gcp.creds.set')
def get_creds():
    toggle_flag('charm.gcp.creds.set', layer.gcp.get_credentials())


@when_all('snap.installed.google-cloud-sdk',
          'charm.gcp.creds.set')
@when_not('endpoint.gcp.requests-pending')
def no_requests():
    gcp = endpoint_from_name('gcp')
    layer.gcp.cleanup(gcp.relation_ids)
    layer.status.active('ready')


@when_all('snap.installed.google-cloud-sdk',
          'charm.gcp.creds.set',
          'endpoint.gcp.requests-pending')
def handle_requests():
    gcp = endpoint_from_name('gcp')
    try:
        for request in gcp.requests:
            layer.status.maintenance('granting request for {}'.format(
                request.unit_name))
            if not request.has_credentials:
                creds = layer.gcp.create_account_key(request.model_uuid,
                                                     request.application_name,
                                                     request.relation_id)
                request.set_credentials(creds)
            if request.instance_labels:
                layer.gcp.label_instance(
                    request.instance,
                    request.zone,
                    request.instance_labels)
            if request.requested_instance_inspection:
                layer.gcp.enable_instance_inspection(
                    request.model_uuid,
                    request.application_name)
            if request.requested_network_management:
                layer.gcp.enable_network_management(
                    request.model_uuid,
                    request.application_name)
            if request.requested_security_management:
                layer.gcp.enable_security_management(
                    request.model_uuid,
                    request.application_name)
            if request.requested_block_storage_management:
                layer.gcp.enable_block_storage_management(
                    request.model_uuid,
                    request.application_name)
            if request.requested_dns_management:
                layer.gcp.enable_dns_management(
                    request.model_uuid,
                    request.application_name)
            if request.requested_object_storage_access:
                layer.gcp.enable_object_storage_access(
                    request.model_uuid,
                    request.application_name)
            if request.requested_object_storage_management:
                layer.gcp.enable_object_storage_management(
                    request.model_uuid,
                    request.application_name)
            layer.gcp.log('Finished request for {}'.format(request.unit_name))
        gcp.mark_completed()
    except layer.gcp.GCPError:
        layer.gcp.log_err(format_exc())
        layer.status.blocked('error while granting requests; '
                             'check credentials and debug-log')


@hook('pre-series-upgrade')
def pre_series_upgrade():
    layer.status.blocked('Series upgrade in progress')
