# Multi-stage: build the React app with Node, then serve the static files + API
# proxy with a tiny nginx image.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# App title is configurable so the public repo ships generic while a personal
# build can brand it. Vite only inlines VITE_-prefixed vars at build time.
ARG VITE_APP_TITLE="Job Scout"
ENV VITE_APP_TITLE=$VITE_APP_TITLE
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
