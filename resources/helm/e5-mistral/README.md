# E5 Mistral Helm Chart

Deploys the `intfloat/e5-mistral-7b-instruct` embedding model through vLLM.
It requests one NVIDIA GPU and can schedule on the cluster's `g5-gpu` or
`g6e-gpu` tainted GPU nodes.

```sh
helm upgrade --install e5-mistral ./helm --namespace $NAMESPACE
```
