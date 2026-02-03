# Kubernetes Helm Profile Contexts

This guide defines the two supported Kubernetes/Helm runtime contexts:

1. `k8s-job` profile (`SANDBOX_PROVIDER=k8s`)
2. `microsandbox` profile (`SANDBOX_PROVIDER=microsandbox`)

Profiles:
- `helm/csv-analyst-chat/profiles/values-k8s-job.yaml`
- `helm/csv-analyst-chat/profiles/values-microsandbox.yaml`

## Dependencies

Required:
- Docker
- kind
- kubectl
- helm
- make
- curl

Recommended:
- jq

Convenience:
- `make deploy-all-local` provisions the default local profile (`k8s-job`) and runs a functional `/runs` check.

## Profile A: Native K8s Job Executor

```bash
make build-runner-k8s K8S_IMAGE_TAG=dev
make build-agent-k8s K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev
kind load docker-image csv-analyst-runner:dev --name csv-analyst
kind load docker-image csv-analyst-agent:dev --name csv-analyst

kubectl -n csv-analyst create namespace csv-analyst --dry-run=client -o yaml | kubectl apply -f -
kubectl -n csv-analyst create secret generic csv-analyst-llm \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

make helm-install-k8s-job \
  K8S_NAMESPACE=csv-analyst \
  HELM_RELEASE=csv-analyst \
  K8S_IMAGE_REPOSITORY=csv-analyst-agent \
  K8S_IMAGE_TAG=dev \
  HELM_EXTRA_SET="--set image.pullPolicy=Never --set existingSecretName=csv-analyst-llm --set env.LLM_PROVIDER=openai --set env.RUNNER_IMAGE=csv-analyst-runner:dev --set env.K8S_NAMESPACE=csv-analyst"

make k8s-smoke K8S_NAMESPACE=csv-analyst HELM_RELEASE=csv-analyst
```

Functional `/runs` expectation:
- SQL call succeeds with rows from runner Job execution.

## Profile B: MicroSandbox Executor on Kubernetes

This validates configuration and control-plane behavior from Kubernetes.

```bash
make helm-install-microsandbox \
  K8S_NAMESPACE=csv-analyst \
  HELM_RELEASE=csv-analyst-msb \
  K8S_IMAGE_REPOSITORY=csv-analyst-agent \
  K8S_IMAGE_TAG=dev \
  HELM_EXTRA_SET="--set image.pullPolicy=Never --set existingSecretName=csv-analyst-llm --set env.LLM_PROVIDER=openai --set env.MSB_SERVER_URL=http://microsandbox.default.svc.cluster.local:5555/api/v1/rpc"

make k8s-smoke K8S_NAMESPACE=csv-analyst HELM_RELEASE=csv-analyst-msb
```

Functional `/runs` expectation:
- With reachable MicroSandbox server: succeeds.
- Without reachable MicroSandbox server: fails with runner internal connectivity error (expected).

## Quick Validation Commands

```bash
helm lint ./helm/csv-analyst-chat -f ./helm/csv-analyst-chat/profiles/values-k8s-job.yaml
helm lint ./helm/csv-analyst-chat -f ./helm/csv-analyst-chat/profiles/values-microsandbox.yaml

make helm-template-k8s-job | head
make helm-template-microsandbox | head
```
