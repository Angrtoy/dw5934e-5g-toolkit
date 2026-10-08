#!/usr/bin/env bash
set -Eeuo pipefail
[ "$#" = 1 ]||exit 64;curl --fail --silent --show-error --get "$1/cgi-bin/luci/admin/system/ubus" --data-urlencode status=1
