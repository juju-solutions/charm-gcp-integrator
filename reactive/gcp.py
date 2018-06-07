from charms.reactive import (
    when_all,
    when_any,
    when_not,
    set_flag,
    toggle_flag,
    clear_flag,
)
from charms.reactive.relations import endpoint_from_name
from charmhelpers.core import hookenv

from charms import layer


@when_not('charm.gcp.app-ver.set')
def set_app_ver():
    hookenv.application_version_set('1.0')
    set_flag('charm.gcp.app-ver.set')


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
