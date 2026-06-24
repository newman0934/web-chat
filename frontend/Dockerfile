# 前端三個 app(shell / auth / chat)共用此 Dockerfile。
# build context 取 frontend/ 整層,因為各 app 以相對路徑 import ../../contracts(在 app 目錄外)。
# 以 vite preview 服務:Module Federation 的 remote 必須 build+preview(dev 不產生 remoteEntry.js)。
FROM node:20-alpine

ARG APP
WORKDIR /app/${APP}

# 1) 先裝相依(package 沒變就用 layer 快取,不重裝)
COPY ${APP}/package.json ${APP}/package-lock.json ./
RUN npm ci

# 2) 跨 app 契約放到 /app/contracts(對應 ../../contracts)+ app 原始碼
COPY contracts /app/contracts
COPY ${APP}/ ./

# 3) build-time 設定:Vite 內聯到 import.meta.env / vite.config 的 process.env。
#    localhost 預設值適用「host 對應埠」的本機 compose;部署他處時於 build args 覆寫。
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_WS_BASE_URL=ws://localhost:8000
ARG VITE_AUTH_REMOTE=http://localhost:5001/assets/remoteEntry.js
ARG VITE_CHAT_REMOTE=http://localhost:5002/assets/remoteEntry.js
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_BASE_URL=$VITE_WS_BASE_URL \
    VITE_AUTH_REMOTE=$VITE_AUTH_REMOTE \
    VITE_CHAT_REMOTE=$VITE_CHAT_REMOTE
RUN npm run build

# 4) preview 綁 0.0.0.0 讓容器外可連(埠由各 app 的 preview script 指定:5000/5001/5002)
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]
