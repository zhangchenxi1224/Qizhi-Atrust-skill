# 客户端适配与持久化分流

## 选择配置路径

| 客户端 | 处理方式 |
| --- | --- |
| Clash Verge Rev / Mihomo | 可使用附带的 JS 候选生成器；读取当前订阅及其已有扩展，组合函数，核实内核支持的规则语法。 |
| macOS 的 Mihomo / Clash.Meta 客户端 | 先确定实际内核与版本，再使用等效配置；界面名称相近不代表扩展机制相同。 |
| Surge / Stash | 查询当前官方文档，使用该客户端的 HTTP 代理、规则和模块 / 覆写语法；不能原样写入 Mihomo JS。 |
| sing-box / v2rayN 等 | 使用对应版本的 outbound 与 route schema，保留原出站和路由；验证本地 HTTP 上游及域名规则能力。 |
| 无法注入分流的其他 VPN | 询问用户是否允许添加支持分流的代理层，或使用指定浏览器 / 应用代理。不能声称任意 VPN 都可无配置兼容。 |

多个客户端并存时，确认负责外网流量的是哪一个，避免同时开启多个 TUN 抢路由。已有原生 aTrust 不自动删除；本流程登录的是容器内 aTrust。

## Mihomo 候选生成

```text
python <skill>/scripts/prepare.py overlay --output <新候选.js> --vpn-ip <真实公网IP> --cas-ip <真实公网IP> --node-name Qizhi-aTrust-HTTP --group-name Qizhi-VPN
```

候选创建 HTTP 节点指向 `127.0.0.1:18080`（非默认端口加 `--http-port`），组仅包含这个节点，不绑定 WLAN / Ethernet 等物理网卡。节点或组重名且含义不匹配时生成函数会拒绝，选择唯一名称，不覆盖用户节点。

前置规则为：loopback 直连，VPN / CAS 认证域及其真实 IP 直连，启智域 UDP 拒绝，`DOMAIN-SUFFIX,sii.edu.cn` 走启智组。随后保留用户原规则的顺序、节点、组及其选择；重复应用不会增加重复规则。为认证入口设置真实 hosts 和 fake-ip 排除，避免建立隧道时循环。

默认适用于已经使用 Rule 模式的用户。不要自动给这类用户加一个会截断原规则的 `MATCH`。

## 原先 Global 模式的特殊情况

从本地控制器读取实际 mode、GLOBAL 当前选择及代理链。Global 模式不执行域名规则，启用分流需要切为 Rule。

- 用户希望保持其他网站当前出口：只在其明确意图成立时添加 `--external-fallback <已存在的节点或策略组>`，在启智规则后追加该 `MATCH`；保留其余原规则备查。原 Global 出口是另一个会变动的组时保留该组，不随意固定其当前叶节点。
- 用户希望按原配置文件重新分流：不传 `--external-fallback`，保留原规则。
- 意图未确定时交互询问一次；已在会话授权或本机状态明确时不重复问。

旧部署可能采用 `SII-aTrust` / `Qizhi-Compute`，也可能使用其他名称；从实际配置读取，登记一致即可。不要把某台机器的外网节点名称或兜底策略写给其他用户。

## 应用与校验

1. 将现有配置、订阅扩展和运行时 mode / 组选择备份到本机私有目录，避免报告中出现订阅 URL、token 和节点密码。
2. 定位当前 profile 及真正生效的扩展。已有 `main(config)` 需要先执行旧函数，再将结果交给启智 overlay；采用独立作用域包装，避免函数或常量冲突。若旧函数是异步，保留调用约定。不要直接覆盖整个用户脚本。
3. 生成最终候选配置，运行当前内核的配置校验（如 `mihomo -t -f <候选>`）。有些旧 Clash 不支持 AND / NETWORK，先核实能力或使用该客户端可表达的等效限制。
4. 使用客户端的持久化配置机制应用并重载。不能只写入下次重启会被生成器覆盖的文件。检查实际 mode 为 Rule，组选择正确，原节点与其他规则保留。
5. 通过连接记录观察 QZ 的链含启智 HTTP 节点，Google / GitHub / ChatGPT 等至少两个外网仍走原有路线；与变更前基线比较。浏览器直接打开平台验证系统代理 / TUN。

不要将整个 `10.0.0.0/8` 或所有私有地址送进启智。需要 SSH、直接 IP、其他业务域名时读取平台给出的具体地址，做最窄规则并验证。HTTP CONNECT 能否承载目标端口取决于代理和服务端策略，不能推断所有协议通用。

文档：[Mihomo HTTP 代理](https://wiki.metacubex.one/config/proxies/http/)、[规则](https://wiki.metacubex.one/config/rules/)、[Clash Verge 脚本](https://www.clashverge.dev/guide/script.html)。适配时核对实际版本。
