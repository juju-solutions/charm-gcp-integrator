# Overview

This charm acts as a proxy to GCP and provides an [interface][] to apply a
certain set of changes via roles, profiles, and tags to the instances of
the applications that are related to this charm.

## Usage

When on GCP, this charm can be deployed, granted trust via Juju to access GCP,
and then related to an application that supports the [interface][].

For example, [CDK][] has [pending support][PR] for this, and can be deployed
with the following bundle overlay:

```yaml
applications:
  kubernetes-master:
    charm: cs:~johnsca/kubernetes-master
  kubernetes-worker:
    charm: cs:~johnsca/kubernetes-worker
  gcp:
    charm: cs:~johnsca/gcp
    num_units: 1
relations:
  - ['gcp', 'kubernetes-master']
  - ['gcp', 'kubernetes-worker']
```

Using Juju 2.4-beta1 or later:

```
juju deploy cs:canonical-kubernetes --overlay ./k8s-gcp-overlay.yaml
juju trust gcp
```

To deploy with earlier versions of Juju, you will need to provide the cloud
credentials via the `credentials`, charm config options.


[interface]: https://github.com/juju-solutions/interface-gcp
[CDK]: https://jujucharms.com/canonical-kubernetes
[PR]: https://github.com/kubernetes/kubernetes/pull/62354
