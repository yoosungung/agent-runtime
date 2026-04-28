#!/usr/bin/env bash
set -euo pipefail

# Usage: kaniko-build.sh <dockerfile> <destination>
# Env: GIT_REPO (required), GIT_REF (default: main), NAMESPACE (default: runtime)

DOCKERFILE=${1:?dockerfile required}
DESTINATION=${2:?destination required}
GIT_REPO=${GIT_REPO:?GIT_REPO is required}
GIT_REF=${GIT_REF:-main}
NAMESPACE=${NAMESPACE:-runtime}

# Strip protocol prefix — token will be injected at runtime via env
GIT_HOST=$(echo "$GIT_REPO" | sed 's|https://||; s|http://||')

SAFE_NAME=$(echo "$DESTINATION" | sed 's|.*/||; s/:/-/g' | tr '[:upper:]' '[:lower:]' | cut -c1-40)
JOB_NAME="kaniko-${SAFE_NAME}-$(date +%s)"

echo "building: $DESTINATION (dockerfile: $DOCKERFILE, ref: $GIT_REF)"

kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB_NAME
  namespace: $NAMESPACE
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: kaniko
        image: gcr.io/kaniko-project/executor:debug
        command: ["/busybox/sh", "-c"]
        args:
          - |
            /kaniko/executor \
              --dockerfile=$DOCKERFILE \
              --context=git://oauth2:\${GIT_TOKEN}@${GIT_HOST}#refs/heads/$GIT_REF \
              --destination=$DESTINATION \
              --cache=true \
              --cache-repo=$(echo "$DESTINATION" | sed 's|:.*||')/cache
        env:
        - name: GIT_TOKEN
          valueFrom:
            secretKeyRef:
              name: git-creds
              key: token
        volumeMounts:
        - name: docker-config
          mountPath: /kaniko/.docker
      volumes:
      - name: docker-config
        secret:
          secretName: ncr-creds
          items:
          - key: .dockerconfigjson
            path: config.json
EOF

echo "submitted: $JOB_NAME (running in cluster)"
echo "  status: kubectl get -n $NAMESPACE job/$JOB_NAME"
echo "  logs:   kubectl logs -n $NAMESPACE -l job-name=$JOB_NAME -f"
