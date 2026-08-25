{{- define "codeUnderstanding.consoleRouteHost" -}}
{{- if .Values.consolePlugin.streamlitRouteHost -}}
{{- .Values.consolePlugin.streamlitRouteHost | trimPrefix "https://" | trimPrefix "http://" -}}
{{- else -}}
{{- $route := lookup "route.openshift.io/v1" "Route" .Values.namespace "code-understanding-console" -}}
{{- if $route -}}
{{- $route.spec.host -}}
{{- else -}}
{{- $domain := .Values.clusterDomain | default "cluster.local" -}}
{{- if hasPrefix "apps." $domain -}}
{{- printf "code-understanding-console-%s.%s" .Values.namespace $domain -}}
{{- else -}}
{{- printf "code-understanding-console-%s.apps.%s" .Values.namespace $domain -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "codeUnderstanding.consolePluginHref" -}}
{{- $consoleRoute := lookup "route.openshift.io/v1" "Route" "openshift-console" "console" -}}
{{- if $consoleRoute -}}
{{- printf "https://%s/code-understanding" $consoleRoute.spec.host -}}
{{- else if .Values.consolePlugin.consoleBaseUrl -}}
{{- printf "%s/code-understanding" .Values.consolePlugin.consoleBaseUrl -}}
{{- else -}}
{{- printf "https://console-openshift-console.apps.%s/code-understanding" (.Values.clusterDomain | default "cluster.local") -}}
{{- end -}}
{{- end -}}
