{{- define "los-agents.name" -}}
genomes-agentic-os-los-agents
{{- end }}

{{- define "los-agents.labels" -}}
app.kubernetes.io/name: {{ include "los-agents.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
