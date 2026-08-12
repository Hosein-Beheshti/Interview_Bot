FROM node:25-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
ARG VITE_GOOGLE_CLIENT_ID
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY templates/ /etc/nginx/templates/
# Restrict envsubst to our own names so nginx's $host, $remote_addr, $upstream
# and friends are left alone by the image's template step.
ENV NGINX_ENVSUBST_FILTER=API_
# Defaults are the docker-compose topology. A deployment that puts the backend
# elsewhere (Railway private networking, say) overrides these at runtime; both
# must be set, since an unset name would render as an empty directive.
ENV API_UPSTREAM=http://backend:8000
ENV API_RESOLVER=8.8.8.8
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
