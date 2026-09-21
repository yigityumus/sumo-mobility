#!/bin/sh
set -eu

alias_name=campus-local
policy_name=campus-simulation-app
policy_path=/tmp/campus-simulation-app-policy.json

mc alias set \
  "$alias_name" \
  http://minio:9000 \
  "$MINIO_ROOT_USER" \
  "$MINIO_ROOT_PASSWORD"

mc mb --ignore-existing "$alias_name/$MINIO_BUCKET"
mc mb --ignore-existing "$alias_name/$MINIO_REFERENCE_BUCKET"
mc admin user add \
  "$alias_name" \
  "$MINIO_APP_USER" \
  "$MINIO_APP_PASSWORD" 2>/dev/null \
  || mc admin user enable "$alias_name" "$MINIO_APP_USER"
printf '%s' \
  "$(
    while IFS= read -r policy_line; do
      case "$policy_line" in
        *"__BUCKET__"*)
          prefix=${policy_line%%__BUCKET__*}
          suffix=${policy_line#*__BUCKET__}
          printf '%s%s%s\n' "$prefix" "$MINIO_BUCKET" "$suffix"
          ;;
        *"__REFERENCE_BUCKET__"*)
          prefix=${policy_line%%__REFERENCE_BUCKET__*}
          suffix=${policy_line#*__REFERENCE_BUCKET__}
          printf '%s%s%s\n' "$prefix" "$MINIO_REFERENCE_BUCKET" "$suffix"
          ;;
        *)
          printf '%s\n' "$policy_line"
          ;;
      esac
    done < /config/app-policy.json
  )" > "$policy_path"
mc admin policy create \
  "$alias_name" \
  "$policy_name" \
  "$policy_path" 2>/dev/null \
  || true
mc admin policy attach \
  "$alias_name" \
  "$policy_name" \
  --user "$MINIO_APP_USER"
