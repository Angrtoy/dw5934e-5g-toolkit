#!/bin/sh
# Read OpenWrt ar/IPK metadata without installing it.  Requires ar and tar.
set -eu
action=${1:?missing-action}
ipk=${2:?missing-ipk}
member=$(ar t "$ipk" 2>/dev/null | awk '/^control\.tar/ {print; exit}')
[ -n "${member:-}" ] || { echo 'IPK_META_ERROR=no-control-archive' >&2; exit 1; }
case "$action" in
	control)
		case "$member" in
			*.tar.gz) ar p "$ipk" "$member" | tar -xOzf - ./control 2>/dev/null ;;
			*.tar.xz) ar p "$ipk" "$member" | tar -xOJf - ./control 2>/dev/null ;;
			*.tar) ar p "$ipk" "$member" | tar -xOf - ./control 2>/dev/null ;;
			*) echo 'IPK_META_ERROR=unsupported-control-compression' >&2; exit 1 ;;
		esac
		;;
	data-contains)
		needle=${3:?}
			data=$(ar t "$ipk" 2>/dev/null | awk '/^data\.tar/ {print; exit}')
		[ -n "${data:-}" ] || exit 1
		case "$data" in
			*.tar.gz) ar p "$ipk" "$data" | tar -xOzf - 2>/dev/null | grep -Fq -- "$needle" ;;
			*.tar.xz) ar p "$ipk" "$data" | tar -xOJf - 2>/dev/null | grep -Fq -- "$needle" ;;
			*.tar) ar p "$ipk" "$data" | tar -xOf - 2>/dev/null | grep -Fq -- "$needle" ;;
			*) exit 1 ;;
		esac
		;;
	*) exit 2;;
esac
