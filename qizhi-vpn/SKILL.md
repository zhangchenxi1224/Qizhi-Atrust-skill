---
name: qizhi-vpn
description: 部署、启动和排查启智（SII）VPN。用户说“启动启智 VPN”“登录启智 aTrust”“配置启智分流”“Docker 隔离 aTrust”或要求启智与现有 Clash Verge、macOS 代理或其他 VPN 并用时使用。检查现有代理、Docker 和登录状态，按需安装并部署容器，保留其他网站的原有分流，通过本机加密凭据完成正常登录并验证两边网络。
---

# 启智 VPN

## 目标与入口

把 aTrust 放在本机 Docker 的独立网络中，通过容器 HTTP 代理承接启智业务流量。默认 `sii.edu.cn` 的业务流量走 aTrust，建立 VPN 所需的 `vpn.sii.edu.cn`、`cas.sii.edu.cn` 公网认证入口直连；其他网站继续使用用户现有客户端的规则和节点。不要把某台机器的外网节点名、磁盘路径或端口当作通用默认值。

- “启动 / 登录 / 打开启智 VPN”：先执行下面的日常启动流程，优先复用已有安装与会话。
- “安装 / 配置 / 换电脑 / 修复未部署环境”：读取 [setup.md](references/setup.md)，完成检查、部署、登录、持久化分流和验证。
- 分流适配读取 [clients.md](references/clients.md)；认证读取 [login.md](references/login.md)；异常读取 [troubleshooting.md](references/troubleshooting.md)。只读取当前需要的参考文件。
- “启智节点红色 / 测速超时，但网站能访问”：读取 [latency.md](references/latency.md)，分别检查内核测速和界面保存的组测速地址，不能仅凭内核测试成功就宣称界面已修复。

命令中的 `<skill>` 指本 SKILL.md 所在目录。Windows 使用可用的 Python 3，macOS 通常使用 `python3`。缺失解释器时从可信的系统包管理器或官方安装源安装。脚本使用标准库；读取 Mihomo YAML 的验证功能需要 PyYAML，优先装到本技能状态目录下的虚拟环境，记录该解释器路径供后续使用。

## 日常一键启动

1. 执行 `python <skill>/scripts/qizhi_vpn.py status`。若没有本机记录，执行 `doctor` 并按 setup.md 寻找和接管现有部署，找不到才安装。
2. 检查已确定的外网客户端是否运行，未运行时通过已登记或 doctor 检测到的安装路径启动，保留其原节点选择；多个客户端用途不明确才询问。然后执行 `python <skill>/scripts/qizhi_vpn.py start`。它启动已安装 Docker 和现有容器；健康容器不会被重建、重启或升级。根据返回 JSON 判断结果，进程退出码 0 不代表 VPN 已登录。
3. `vpn_ready` 表示受保护的启智入口经容器代理可达。若为 `needs_login_or_diagnosis`，检查容器 UI 和网络原因，不能仅凭 aTrust 进程、虚拟网卡或容器 running 判断登录。需要认证时读取 login.md，使用保存的凭据继续正常登录。
4. 执行 `python <skill>/scripts/qizhi_vpn.py verify`。确认启智经过 aTrust，至少两个外网网站继续走原客户端。若 `connectivity_verified_needs_route_check`，继续用客户端连接记录检查实际路线，不能宣称已完成分流验证。
5. 简短汇报启智和外网的实际结果及需要用户处理的事项。不要停在“脚本已运行”或只给用户手动步骤；有工具和授权时完成正常浏览器登录。

“一键”指 agent 执行上述完整流程；短信验证码、扫码、系统权限和需要用户完成的认证不能无人值守绕过。已有会话有效时不重新索取密码或验证码。

## 本机状态与凭据

部署登记保存在技能目录之外：Windows `%LOCALAPPDATA%/QizhiVPN`；macOS `~/Library/Application Support/QizhiVPN`；Linux `$XDG_STATE_HOME/qizhi-vpn`（默认 `~/.local/state/qizhi-vpn`）。可用 `QIZHI_VPN_STATE_DIR` 指定私有状态目录。

- `state.json`：部署路径、容器名、Docker context、客户端类型、本地代理和控制器配置路径，不存密码。
- Windows：`credentials.dpapi`，使用当前 Windows 用户的 DPAPI 加密，目录限制当前用户和 SYSTEM。
- macOS：系统钥匙串，service 为 `qizhi-vpn.sii.edu.cn`。Linux 仅接受 Secret Service / KWallet 加密后端，不退回明文。
- `last-verification.json`：最近的可达性与路由检查结果，不包含凭据。

`credentials.py status` 只显示保存状态。用户已授权记住账号密码时，可用 `credentials.py save --stdin` 接收 `{"username":"…","password":"…"}`；使用工具的输入通道传递，不把秘密拼进命令行参数或明文临时文件。也可在本机交互终端运行 `save`，密码由 getpass 隐藏输入。

仅在实际授权的 CAS 登录需要时调用 `credentials.py read --reveal`；优先在工具的私有执行上下文内读取并填写，不把输出回显到普通日志、回复、截图描述或分享包。当前工具必须返回凭据才能填写时，限制为这次认证上下文，不重复展示。一次性验证码绝不保存。不要读取或复用无关账号。

## 分流与安全边界

1. 先识别正在使用的客户端与实际运行模式，读取现有配置后备份到本机私有目录。多个客户端用途不明时，交互询问哪个管理外网，不能擅自替换。
2. 默认把启智规则放在原规则之前，保留其余节点、组、选择和规则顺序。原本是 Global 模式时，切换 Rule 才能分流；先依据用户已表达的意图选择“保持当前外网出口”或“恢复原规则分流”，仍不明确才询问并保存决定。不要给所有用户硬编码 `MATCH,Proxy`。
3. 使用客户端支持的持久化扩展机制，不只改临时生成配置。验证新配置后才加载；已有扩展函数必须组合，不能覆盖丢失原逻辑。
4. 代理和 noVNC 仅监听宿主机 `127.0.0.1`。容器不使用 host 网络，不给宿主机启动原生 aTrust。保留已有 VPN 安装，不自动禁用或卸载。
5. 验证认证网关真实公网 IP，不能把 Clash 的 `198.18.0.0/15` fake-IP 写入容器 hosts。启智 HTTP 代理不支持 UDP，规则明确拒绝该域的 UDP，浏览器使用 TCP；其他协议或内网 IP 按实际业务单独适配。
6. 容器代理添加防漏规则：新出站只能进入实际 VPN 隧道。VPN 失效时启智业务失败，其他网站继续原有路线。认证公网入口是有意保留的直连例外。

## 完成标准

安装任务完成需有：容器受保护入口可达、宿主机启智连接实际走 aTrust、至少两个外网站点走原客户端、分流配置持久化的证据。首次部署可在可恢复且不影响用户现有任务时进行短暂断开测试，并立即恢复；日常启动不重复中断测试。必要时区分“网络可达”和“平台网页已登录”，以及“网页版”和另行认证的 CLI / SSH。

使用本机事实报告支持范围。此技能在 Windows amd64 现有部署上验证；macOS / Apple Silicon 和其他客户端提供检测与适配流程，需在目标机验证镜像架构、客户端语法及登录能力后再宣称成功。
