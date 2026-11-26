# 启智测速误报：内核与界面分别修复

## 判断真实断线还是测速目标不合适

先运行 `qizhi_vpn.py status`，检查容器 HTTP 代理能否访问 `https://qz.sii.edu.cn/`。不通时先诊断登录和网络，不用修改测速地址掩盖断线。

启智通路正常时，读取当前内核控制器、profile UID、启智节点与组名。通过本地控制器对启智节点执行 `/proxies/<编码后的节点名>/delay?url=https%3A%2F%2Fqz.sii.edu.cn%2F&timeout=5000`。控制器 secret 只放内存请求头。不能将页面跳转 302 误认为超时；受保护入口的 302 只证明网络通路，不证明网页用户已登录。

在当前客户端持久化扩展里为启智组设置 `url: https://qz.sii.edu.cn/` 和 `expected-status: 200/302`，只更新该组。附带 overlay 已提供这两个字段。其他节点、组、选择、规则及全局测速地址保持原值。

## Clash Verge 界面设置

Clash Verge Rev 2.4.0 的界面还从 Local Storage 的 `proxy-head-state` 读取：

```text
proxy-head-state[当前 profile UID][启智组名].testUrl
```

界面测速优先使用该字段，再使用组的 `testUrl` 和全局默认地址；全部缺失时回落到 Cloudflare。该版本的组件更新依赖未包含组 URL，内核运行中更新配置后，已挂载的界面可能仍用旧地址。

优先用当前允许的界面工具，在启智组的“测速地址”中填入 `https://qz.sii.edu.cn/` 并重新测速。只要有工具和授权就完成操作；不要仅把手动步骤交给用户。无法使用界面工具时，可按下文离线修正本地状态。

源码依据：[组状态存储](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.0/src/components/proxy/use-head-state.ts)、[组测速地址选择](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.0/src/components/proxy/proxy-head.tsx)。其他版本先核对其实际实现，不猜测存储位置或字段。

## Windows WebView2 的离线修复

`scripts/verge_latency.cjs` 使用 LevelDB API 修改一条配置记录。它不会操作进程，也不使用其他用户的固定路径、profile UID 或组名。该方法针对已经核实采用相同存储格式的 WebView2 客户端；macOS 或其他存储引擎使用该客户端自己的设置机制。

1. 从当前机器读取正在生效的 `profiles.yaml.current`、启智组名称、Clash Verge 安装路径和 WebView2 数据目录。Windows 常见位置是 `%LOCALAPPDATA%/io.github.clash-verge-rev.clash-verge-rev/EBWebView/Default/Local Storage/leveldb`。检查实际目录，不能原样套用另一台机器的路径。
2. 用 `credentials.private_dir` 创建技能状态目录之外或其下的私有工作目录，保存配置语义、组选择、原内核 PID 和代理 / 控制器端口基线。备份不能进入 GitHub 或分享包。
3. 只在需要离线修复时安装工具依赖：在 `<skill>/scripts` 目录执行 `npm ci --ignore-scripts --no-audit --no-fund`。依赖固定为 `classic-level`，不上传 `node_modules`。运行 `node <skill>/scripts/test_verge_latency.cjs` 可做隔离回归检查。
4. 检查正在运行的应用时，先把 LevelDB 文件复制到私有快照目录（跳过被占用的 `LOCK`），在快照上运行 `inspect`；不要打开正在使用的实际数据库。

```text
node <skill>/scripts/verge_latency.cjs inspect --database <快照目录> --profile <当前UID> --group <启智组名>
```

5. 需要写入时，短暂关闭明确识别的 Clash Verge 界面进程，等待其 WebView 释放数据库锁。保持原内核和其他应用运行；若系统拒绝操作，解释具体阻碍，不绕过。将应用重开置于 `finally`，避免异常导致界面一直关闭。在 Windows 启动后台应用使用隐藏窗口参数。
6. 在实际数据库上执行下列命令，备份目录须为空、位于数据库之外，并预先限制访问权限。脚本会备份数据库及原字段，原样保存其他 profile 和组；重复运行不重复写入。

```text
node <skill>/scripts/verge_latency.cjs patch --database <实际leveldb目录> --profile <当前UID> --group <启智组名> --backup <私有目录>/backup-latency
```

7. 重开界面后重新从快照读回字段，并进行真实测速。重开可能触发客户端重新生成 YAML；比较配置语义而非仅比较文件哈希。确认原节点、规则、选择、模式和全局测速设置一致。

重开界面时，某些安装可能额外启动一个无法绑定端口的内核进程。不要终止原来承担流量的内核；先核对 PID、父进程、创建时间与监听端口。只有确认是本次重开新建、且未承接流量的冗余进程，才进行清理；之后再次检查网络。不能无依据声称重开界面始终不会触及内核生命周期。

## 验收与报告

- 读回实际保存的启智组 `testUrl`，检查客户端重新加载后仍存在。
- 内核对该 URL 的真实测速成功；有界面工具时触发组测速并检查结果或请求 URL。
- 确认外网至少两个网站仍按原客户端路径工作。
- 只能在观察到界面结果时声称红字已经消失；否则报告已持久化的字段和实际测速结果，不把内核结果冒充界面观察。

不要把所有组的测速地址改成启智，也不要为通过 Cloudflare 测速而放宽 aTrust 容器的出站限制。全局组若包含用途不同的节点，其统一测速不代表启智专用组的健康状态。
