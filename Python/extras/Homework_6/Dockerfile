FROM node:22-alpine AS map_assets
WORKDIR /assets
RUN npm install --no-audit --no-fund --ignore-scripts leaflet@1.9.4

FROM python:3.12-alpine
WORKDIR /app
COPY *.py ./
COPY web ./web
COPY --from=map_assets /assets/node_modules/leaflet/dist/leaflet.js ./web/leaflet.js
COPY --from=map_assets /assets/node_modules/leaflet/dist/leaflet.css ./web/leaflet.css
COPY --from=map_assets /assets/node_modules/leaflet/LICENSE ./web/leaflet-license.txt
