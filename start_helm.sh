make helm-install \
    K8S_IMAGE_REPOSITORY=csv-analyst-agent \
    K8S_IMAGE_TAG=dev \
    K8S_SANDBOX_PROVIDER=k8s \
    HELM_EXTRA_SET="--set env.RUNNER_IMAGE=csv-analyst-runner:dev --set
  env.K8S_NAMESPACE=csv-analyst"

kubectl -n csv-analyst rollout status deploy/csv-analyst-csv-analyst-chat --timeout=180s 
make k8s-smoke
