# EarthAI 局域网静态资源交付

## 已本地化

- **字体**：下载 DM Sans、Noto Sans SC 全部 103 个 WOFF2 子集，约 4.56 MB，保留原界面字体和 400–700 可变字重，不是只截取当前页面文字的临时字库。`unicode-range` 使浏览器只请求实际用到的子集。
- **Swagger UI**：固定 `swagger-ui-dist@5.34.0`，JavaScript、CSS 均在本地，复用 EarthAI favicon；关闭外部 schema validator，OpenAPI 从本站读取。
- **ReDoc**：固定与 FastAPI 经典脚本模板兼容的 `redoc@2.5.4`，脚本及内置 Logo 均在本地，禁用 Google Fonts。原脚本中的 CDN Logo URL 仅改写为站内路径，保留品牌标识和许可证。
- **既有资源**：React、路由、Lucide 图标等原已打包进站内 JavaScript；favicon、Apple Touch 图标及 manifest 原已是本站资源。没有遗漏要另行抓取的远程页面图片。

## 文件位置

- `frontend/public/fonts/`：字体 CSS、103 个字体文件、两份 SIL Open Font License 和来源/校验清单 `manifest.json`。
- `frontend/public/vendor/docs/`：文档资源、Apache-2.0/MIT 许可证及来源/校验清单 `manifest.json`。
- `frontend/index.html`：直接加载 `/fonts/fonts.css`；`frontend/src/styles.css` 不再使用 Google Fonts `@import`。
- `backend/main.py`：自托管 `/api/docs`、`/redoc` 和 OAuth 文档回调；`/api/openapi.json` 不变。
- `frontend/dist/`：已重新构建，包含上述全部资源；现有 Dockerfile 会完整复制它，不需要改动镜像内路径。

源码 ZIP 同时包含原始公共资源及完整前端构建产物，且不包含账号、凭据、正式数据库、上传文件或私有部署配置。

## 验证结果

- `pytest -q`：361 项通过，1 条既有 Starlette/AnyIO 弃用警告。
- `ruff check backend tests scripts`：通过。
- 前端 49 项测试、TypeScript 检查、Vite 生产构建：通过。
- 所有字体 WOFF2 文件、文档资源的校验摘要一致；公共目录与构建目录文件内容一致。
- 无头 Chromium 在**拒绝所有非本站请求**的条件下完成注册登录、12 个管理路由、Swagger、ReDoc，以及 390px 移动端验收。中英文字体含中间字重已真实加载。外部请求 0、静态资源失败 0、页面运行错误 0。

原始结果为 `local-static-verification.json`。可重复验收脚本为 `tests/local-static-browser.cjs`，只应连接隔离测试实例，不能用它在正式实例创建测试账号。

## 局域网与完全断网的边界

**网页和 API 文档显示不再需要公网静态资源**。正常启动不会下载字体、脚本或图片，不需要开放 Google Fonts、jsDelivr、Redocly 等 CDN 域名。

模型供应商 API、SSH/Kubernetes 集群和用户手动打开的远程智能体仍属于实际业务连接，没有改成假数据或禁用。如果部署环境完全隔离，需配置可从该环境访问的内网模型和目标地址。

首次从源码执行 `pip install`、`npm ci` 或首次拉取 Docker 基础镜像仍属于构建依赖获取，不在网页静态本地化范围。完全离线安装应预先准备所需运行环境/镜像或软件源缓存；交付包中的已构建前端无需在目标机再运行 npm。

`python3 scripts/vendor_fonts.py` 和 `python3 scripts/vendor_docs.py` 是可选的联网重新抓取脚本，保留来源与许可证；正常安装、构建、运行均不会自动调用它们。现有资源已落盘，无需重新抓取。

## 本轮部署状态

检查时当前 Docker 上下文没有 EarthAI 容器，8000 端口未启动。本轮只更新项目文件、构建产物和源码包，没有擅自重新建立服务或挂载原数据卷。浏览器验收使用独立数据目录和临时 `127.0.0.1:8010` 服务，验收后关闭。
