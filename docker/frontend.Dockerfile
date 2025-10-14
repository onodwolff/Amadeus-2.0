FROM node:20-bookworm

WORKDIR /app

ENV NG_CLI_ANALYTICS=false

COPY package.json package-lock.json ./frontend/amadeus-ui/
RUN npm ci --prefix frontend/amadeus-ui

COPY . ./frontend/amadeus-ui

WORKDIR /app/frontend/amadeus-ui

EXPOSE 4200

CMD ["npm", "run", "start", "--", "--host", "0.0.0.0", "--port", "4200"]
