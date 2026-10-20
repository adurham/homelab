#!/bin/sh
echo "--- established connections to 8001/8002 ---"
ss -tnp 2>/dev/null | grep -E ':(8001|8002) ' || echo "none"
echo "--- listener processes ---"
ps -o pid,ppid,lstart,loginuid,tty,cmd -p 3400883,3407865 2>/dev/null
for p in 3400883 3407865; do
  pp=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  [ -n "$pp" ] && [ "$pp" != "1" ] && ps -o pid,ppid,lstart,cmd -p "$pp" 2>/dev/null
done
echo "--- cwd + open fds ---"
for p in 3400883 3407865; do
  echo "pid $p cwd=$(readlink /proc/$p/cwd 2>/dev/null)"
  ls -l /proc/$p/fd 2>/dev/null | awk '{print $9, $10, $11}' | grep -E 'socket|pipe|/root|/tmp' | head -5
done
echo "--- logins around 2026-10-18 23:25-23:40 ---"
journalctl --since '2026-10-18 23:25:00' --until '2026-10-18 23:40:00' --no-pager 2>/dev/null | grep -E 'Accepted|session opened|New session|systemd-logind' | head -10
echo "--- srv.py (first 40 lines) ---"
head -40 /root/boxhelp/srv.py 2>/dev/null
echo "--- boxhelp dir ---"
ls -la /root/boxhelp 2>/dev/null | head -10
