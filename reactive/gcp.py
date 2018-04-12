from charms.reactive import (
    when_all,
    when_any,
    when_not,
    endpoint_from_flag,
    toggle_flag,
    clear_flag,
)

from charms import layer


@when_any('config.changed.credentials')
def update_creds():
    clear_flag('charm.gcp.creds.set')


@when_not('charm.gcp.creds.set')
def get_creds():
    toggle_flag('charm.gcp.creds.set', layer.gcp.get_credentials())


@when_all('snap.installed.gcp-cli',
          'charm.gcp.creds.set')
@when_not('endpoint.gcp.requested')
def no_requests():
    layer.status.maintenance('cleaning up unused gcp entities')
    gcp = endpoint_from_flag('endpoint.gcp.requested')
    layer.gcp.cleanup(gcp.application_names)
    layer.status.active('ready')


@when_all('snap.installed.gcp-cli',
          'charm.gcp.creds.set',
          'endpoint.gcp.requested')
def handle_requests():
    gcp = endpoint_from_flag('endpoint.gcp.requested')
    for request in gcp.requests:
        layer.status.maintenance('granting request for {}'.format(
            request.unit_name))
        if request.instance_tags:
            layer.gcp.tag_instance(
                request.instance,
                request.zone,
                request.instance_labels)
        if request.requested_instance_inspection:
            layer.gcp.enable_instance_inspection(
                request.application_name,
                request.instance,
                request.zone)
        if request.requested_network_management:
            layer.gcp.enable_network_management(
                request.application_name,
                request.instance,
                request.zone)
        if request.requested_load_balancer_management:
            layer.gcp.enable_load_balancer_management(
                request.application_name,
                request.instance,
                request.zone)
        if request.requested_block_storage_management:
            layer.gcp.enable_block_storage_management(
                request.application_name,
                request.instance,
                request.zone)
        if request.requested_dns_management:
            layer.gcp.enable_dns_management(
                request.application_name,
                request.instance,
                request.zone)
        if request.requested_object_storage_access:
            layer.gcp.enable_object_storage_access(
                request.application_name,
                request.instance,
                request.zone,
                request.s3_read_patterns)
        if request.requested_object_storage_management:
            layer.gcp.enable_object_storage_management(
                request.application_name,
                request.instance,
                request.zone,
                request.s3_write_patterns)
        layer.gcp.log('Finished request for {}'.format(request.unit_name))
        request.mark_completed()
    clear_flag('endpoint.gcp.requested')
