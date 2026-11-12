#!/bin/sh
F=/etc/nginx/sites-available/garage
cat > $F <<'EOF'
upstream garage_s3 {
    server 172.16.0.71:3900 max_fails=3 fail_timeout=10s;
    server 172.16.0.72:3900 max_fails=3 fail_timeout=10s;
    server 172.16.0.74:3900 max_fails=3 fail_timeout=10s;
}

server {
    listen 3900;
    server_name _;
    client_max_body_size 0;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_request_buffering off;
    location / {
        proxy_pass http://garage_s3;
    }
}
EOF
ln -sf $F /etc/nginx/sites-enabled/garage
nginx -t 2>&1 | tail -1
systemctl reload nginx
ss -lnt | grep -c ":3900"
