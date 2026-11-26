# 检查、接管与首次部署

## 1. 识别本机环境

运行 `python <skill>/scripts/qizhi_vpn.py doctor`，然后根据输出检查：

- 操作系统、CPU 架构、空闲磁盘、Python / Docker / Compose 是否可用。
- 正在管理外网的客户端及其实际运行模式、节点选择、系统代理 / TUN 状态、配置位置、扩展脚本和本地监听端口。运行时控制器信息优先于旧配置文件；不要输出完整节点配置或控制器 secret。
- Docker 当前 context 是否指向本机 Linux engine；已有 OrbStack 等兼容引擎可以复用。不要无提示切换到远程 context。
- 是否已有 aTrust 容器、数据卷或部署目录；是否已有宿主机原生 aTrust 在影响路由。不要自动卸载、禁用已有 VPN。
- `18080` 和 `16080` 是否被当前部署使用；其他软件占用时选空闲端口，统一更新后续配置和登记。

客户端用途不明确才询问，例如“当前外网由 Clash Verge、Surge 还是其他客户端管理？”能够从配置和既有会话确认的内容不重复问。跨客户端配置不能盲目套用 Mihomo YAML。

找到现有部署时先验证并登记，不新建重复容器。示例：

```text
python <skill>/scripts/qizhi_vpn.py register --deployment-dir <现有部署目录> --client clash-verge --external-proxy http://127.0.0.1:<现有混合端口> --mihomo-config <当前生成的配置.yaml> --node-name <现有启智节点名> --group-name <现有启智组名>
```

按需添加 `--http-port`、`--console-port` 和 `--container`。非 Mihomo 客户端省略 `--mihomo-config`，在其 UI / 连接日志中验证路由。记录已确认的外网策略，供后续重用。

## 2. 按需安装缺失依赖

在用户授权安装部署的范围内自主完成下载、安装和配置，不为常规可逆步骤重复索要许可。使用当前官方安装文档和可信包管理器核对包名及 CPU 架构：

- Windows：用 `winget show Docker.DockerDesktop` 核对来源，再安装；检查 WSL 2 和虚拟化。Docker 首次初始化可能要求系统权限或重启，按实际提示交给用户，不自动重启电脑。只有用户需要新代理客户端且没有可复用客户端时才核实并安装 Clash Verge Rev（例如先查询 `ClashVergeRev.ClashVergeRev` 的当前包信息）。
- macOS：保留现有 Homebrew / Docker Desktop / OrbStack。先查询当前 Docker cask 名称（如 `brew info --cask docker-desktop`），确认官方来源和架构再安装；不要因 Apple Silicon 就强制执行 amd64 镜像。
- Linux：遵循发行版和 Docker 官方安装方法；复用现有 rootless / rootful 部署，不为方便暴露 Docker TCP socket。
- Python / curl / Node（生成 JS 的检查需要）缺失时使用官方源或现有包管理器。不要下载随机安装器。

检查磁盘容量。空间不足时选择有空间的部署盘并向用户说明；不要自动 prune 用户镜像、删除数据卷或迁移 Docker VHDX / 创建目录联接。镜像构建和 Docker 数据所在磁盘都需有足够空间。

官方入口：[Docker Windows](https://docs.docker.com/desktop/setup/install/windows-install/)、[Docker macOS](https://docs.docker.com/desktop/setup/install/mac-install/)、[Clash Verge Rev](https://www.clashverge.dev/)。首次安装应在线核实，不把此文中的版本当作最新版本。

## 3. 准备 Docker 隔离环境

参考 [docker-easyconnect / aTrust](https://github.com/docker-easyconnect/docker-easyconnect/blob/master/README.md)。该项目是运行环境封装，aTrust 客户端本身并非因此变成开源软件。检查镜像 registry 的架构清单并固定经过检查的 digest。原 Windows amd64 部署使用 Debian bookworm 底座 `hagb/docker-atrust@sha256:d564515395c2eabdbd78152ad47ea11e6d01a41b94435509ac1b8ddff79ffe26`；它是历史验证值，不是跨架构或最新版本保证。

先核实两个认证域名的真实公网地址；通过可信公网 DNS / DoH 查询，并结合实际 TLS 连接确认。不能使用本机被 TUN 替换的 fake-IP。在空的私有部署目录生成候选：

```text
python <skill>/scripts/prepare.py docker --directory <新部署目录> --base-image <镜像@sha256:摘要> --platform linux/amd64 --vpn-ip <vpn公网IP> --cas-ip <cas公网IP>
```

Apple Silicon 选择已验证的 `linux/arm64` 镜像；若没有适用镜像，说明限制并确认是否使用模拟运行，不能直接声称支持。模板 Dockerfile 基于 Debian bookworm，使用之前先检查底座发行版、包管理器、`/start.sh`、Tinyproxy 运行 UID、VPN 接口名及客户端浏览器能力；不匹配时先适配模板，再构建。使用实际隧道接口替换模板 `vpn-guard.sh` 中的 `utun7`，并验证它确实承载受保护地址。

模板提供 Chromium 浏览器、CAS 协议处理入口、持久化 `/root` 卷和防漏脚本；只映射本机 HTTP `18080` 与 noVNC `16080`。随机 noVNC 密码保存在私有部署 `.env`。不要把账户密码写入 Compose 环境变量、镜像或仓库。运行：

```text
docker compose config --quiet
docker compose build
docker compose up -d
```

如构建下载需要现有代理，只把当前代理提供给构建过程。`host.docker.internal` 解析陈旧时可在构建时使用 `--add-host host.docker.internal:host-gateway`；不能将错误的宿主机地址写入所有容器或修改全局 hosts。运行时清空继承的 HTTP / HTTPS / ALL_PROXY，避免 aTrust 递归进入 Clash。

防漏脚本只约束容器 Tinyproxy 的新出站连接，允许 loopback 和实际 VPN 隧道；保留 established 回包。启动时先安装规则，再启动 aTrust / Tinyproxy。它必须同时覆盖 IPv4 / IPv6；验证不了时不可宣称 fail-closed 已完成。

## 4. 登录、分流、登记与验证

1. 按 [login.md](login.md) 在容器内部登录，不调用宿主机原生 aTrust。
2. 按 [clients.md](clients.md) 生成候选配置、保留原外网策略、做配置校验，部署到客户端持久化扩展并加载。
3. 登记本机路径和实际端口，运行 `status`、`verify`；通过系统代理 / TUN 的普通宿主机浏览器另开新标签验证平台。命令行显式指定代理只能证明代理路径，不足以证明所有应用均被接管。
4. 检查客户端重载后规则仍在。首次部署在适合中断且能恢复时短停容器：启智业务应失败，至少两个外网仍可用，然后立即启动、重新检查会话和连接；不影响用户正在执行的任务。
5. 备份和回滚脚本留在私有部署目录，不放进分享包。记录实际已测试的域名、外网目标和路由。仅域名分流不自动覆盖所有内网 IP、UDP 或独立 CLI 认证。
