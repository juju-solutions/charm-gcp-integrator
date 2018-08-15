# Overview

This charm acts as a proxy to GCP and provides an [interface][] to apply a
certain set of changes via roles, profiles, and tags to the instances of
the applications that are related to this charm.

## Usage

When on GCP, this charm can be deployed, granted trust via Juju to access GCP,
and then related to an application that supports the [interface][].

For example, [CDK][] has support for this, and can be deployed with the
following bundle overlay:

```yaml
applications:
  gcp-integrator:
    charm: cs:~containers/gcp-integrator
    num_units: 1
relations:
  - ['gcp-integrator', 'kubernetes-master']
  - ['gcp-integrator', 'kubernetes-worker']
```

Then deploy CDK using this overlay:

```
juju deploy cs:canonical-kubernetes --overlay ./k8s-gcp-overlay.yaml
```

The charm then needs to be granted access to credentials that it can use to
setup integrations.  Using Juju 2.4 or later, you can easily grant access to
the credentials used deploy the integrator itself:

```
juju trust gcp-integrator
```

To deploy with earlier versions of Juju, or if you wish to provide it different
credentials, you will need to provide the cloud credentials via the `credentials`,
charm config options.

**Note:** The credentials used must have rights to use the API to inspect the
instances connecting to it, enable a service account for those
instances, assign roles to those instances, and create custom roles.

# Resource Usage Note

By relating to this charm, other charms can directly allocate resources, such
as PersistentDisk volumes and Load Balancers, which could lead to cloud charges
and count against quotas.  Because these resources are not managed by Juju,
they will not be automatically deleted when the models or applications are
destroyed, nor will they show up in Juju's status or GUI.  It is therefore up
to the operator to manually delete these resources when they are no longer
needed, using the Google Cloud console or API.

# Examples

Following are some examples using GCP integration with CDK.

## Creating a pod with a PersistentDisk-backed volume

This script creates a busybox pod with a persistent volume claim backed by
GCE's PersistentDisk.

```sh
#!/bin/bash

# create a storage class using the `kubernetes.io/gce-pd` provisioner
kubectl create -f - <<EOY
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gce-standard
provisioner: kubernetes.io/gce-pd
parameters:
  type: pd-standard
EOY

# create a persistent volume claim using that storage class
kubectl create -f - <<EOY
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: testclaim
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Mi
  storageClassName: gce-standard
EOY

# create the busybox pod with a volume using that PVC:
kubectl create -f - <<EOY
apiVersion: v1
kind: Pod
metadata:
  name: busybox
  namespace: default
spec:
  containers:
    - image: busybox
      command:
        - sleep
        - "3600"
      imagePullPolicy: IfNotPresent
      name: busybox
      volumeMounts:
        - mountPath: "/pv"
          name: testvolume
  restartPolicy: Always
  volumes:
    - name: testvolume
      persistentVolumeClaim:
        claimName: testclaim
EOY
```

## Creating a service with a GCE load-balancer

The following script starts the hello-world pod behind a GCE-backed load-balancer.

```sh
#!/bin/bash

kubectl run hello-world --replicas=5 --labels="run=load-balancer-example" --image=gcr.io/google-samples/node-hello:1.0  --port=8080
kubectl expose deployment hello-world --type=LoadBalancer --name=hello
watch kubectl get svc -o wide --selector=run=load-balancer-example
```


[interface]: https://github.com/juju-solutions/interface-gcp-integration
[api-doc]: https://github.com/juju-solutions/interface-gcp-integration/blob/master/docs/requires.md
[CDK]: https://jujucharms.com/canonical-kubernetes
