FROM nginx:1.29-alpine

COPY apps/debug-chat/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/debug-chat/index.html /usr/share/nginx/html/index.html
COPY apps/debug-chat/app.js /usr/share/nginx/html/app.js
