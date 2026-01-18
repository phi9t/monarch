# GPU collective demo (StatefulSet-only)

This variant uses only native Kubernetes objects (headless `Service` + `StatefulSet` for workers and a simple controller `Pod`). No Volcano or custom schedulers are required.

## How to run

```bash
# 1) Create namespace (once)
kubectl create namespace monarch-tests

# 2) Deploy workers as a StatefulSet with stable DNS + GPU resources
kubectl apply -f manifests/stateful_workers.yaml

# 3) Launch the controller pod
kubectl apply -f manifests/controller.yaml

# 4) Copy the demo script and run it from the controller
kubectl cp main.py monarch-tests/monarch-client-demo:/tmp/main.py
kubectl exec -it monarch-client-demo -n monarch-tests -- /bin/bash
# Inside controller:
python /tmp/main.py --num_hosts=2 --num_gpus_per_host=4
```

## Run locally with k3s (no GPUs; logic only)
If you just want to exercise the control-plane flow without real GPUs:

```bash
# Install k3s (single-node): https://k3s.io
curl -sfL https://get.k3s.io | sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

kubectl create namespace monarch-tests
kubectl apply -f manifests/stateful_workers.yaml
kubectl apply -f manifests/controller.yaml

# Copy and run (will fail if GPUs are required; use to validate wiring)
kubectl cp main.py monarch-tests/monarch-client-demo:/tmp/main.py
kubectl exec -it monarch-client-demo -n monarch-tests -- /bin/bash
# Inside controller, run with CPU-only expectations (will error on torch.cuda use):
python /tmp/main.py --num_hosts=2 --num_gpus_per_host=1
```

### Alternative: k3s in Docker (single-node)
If you prefer a Docker-contained k3s:
```bash
sudo docker run \
  --privileged \
  --name k3s-server-1 \
  --hostname k3s-server-1 \
  -p 6443:6443 \
  -d rancher/k3s:v1.24.10-k3s1 \
  server

# kubeconfig path inside the container
sudo docker exec k3s-server-1 cat /etc/rancher/k3s/k3s.yaml > /tmp/k3s.yaml
export KUBECONFIG=/tmp/k3s.yaml
```

For true GPU testing, use a GPU-capable cluster with NVIDIA device plugin.

### Using a local registry with k3s (recommended)
This keeps the workflow simple and repeatable for developers using local images:
```bash
# Start a local registry (one-time)
REG_NAME=k3s-registry
REG_PORT=5000
docker run -d --restart=always -p 127.0.0.1:${REG_PORT}:5000 --name ${REG_NAME} registry:2

# Tell k3s containerd to trust/pull from the local registry
sudo mkdir -p /etc/rancher/k3s
cat <<'EOF' | sudo tee /etc/rancher/k3s/registries.yaml
mirrors:
  "localhost:5000":
    endpoint:
      - "http://127.0.0.1:5000"
EOF
sudo systemctl restart k3s

# Build and push to the local registry
docker build -t localhost:5000/monarch-local:dev .
docker push localhost:5000/monarch-local:dev

# Deploy manifests
kubectl apply -f manifests/stateful_workers.yaml
kubectl apply -f manifests/controller.yaml

# Point workloads at your local registry tag (after apply)
kubectl -n monarch-tests set image statefulset/monarch-worker worker=localhost:5000/monarch-local:dev
kubectl -n monarch-tests set image pod/monarch-client-demo monarch=localhost:5000/monarch-local:dev
```

## What’s happening
- Workers: `StatefulSet` pods (`monarch-worker-0`, `monarch-worker-1`, …) each run `run_worker_loop_forever` bound to their pod FQDN on port `26600`, exposing a Monarch host endpoint per pod.
- Controller: The Python script builds a `HostMesh` by dialing the pod DNS names, spawns GPU-bound processes per host, and runs a NCCL allreduce via an actor.
- Networking: Headless service `monarch-workers` gives stable DNS (`monarch-worker-$i.monarch-workers.monarch-tests.svc.cluster.local`).
- GPU isolation: Each worker pod requests its own GPUs; per-process GPU binding happens inside the actor via `LOCAL_RANK`.
