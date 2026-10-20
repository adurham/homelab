#!/bin/sh
echo "--- users ---"
pveum user list --output-format json 2>/dev/null | tr '}' '\n' | sed -n 's/.*"userid":"\([^"]*\)".*"tfa":"\([^"]*\)".*/\1 tfa=\2/p'
echo "--- tokens ---"
pveum user list --output-format json 2>/dev/null | tr '}' '\n' | sed -n 's/.*"userid":"\([^"]*\)".*/\1/p' | while read -r u; do
  t=$(pveum user token list "$u" --output-format json 2>/dev/null)
  case "$t" in
    ''|'[]') ;;
    *) echo "TOKEN $u -> $t" ;;
  esac
done
echo "--- acl ---"
pveum acl list 2>/dev/null | head -15
echo "--- backup jobs ---"
pvesh get /cluster/backup --output-format json 2>/dev/null | tr '}' '\n' | grep -E '"id"' | cut -c1-160
echo "--- recent vzdump tasks (all nodes) ---"
pvesh get /cluster/tasks --typefilter vzdump --limit 6 --output-format json 2>/dev/null | tr '}' '\n' | grep -E '"status"|"starttime"' | cut -c1-120
