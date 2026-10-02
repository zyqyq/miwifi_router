# MiWiFi Router - Home Assistant Custom Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/tiejiang29/miwifi_router)](https://github.com/tiejiang29/miwifi_router)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-blue)](https://www.home-assistant.io/)

小米 MiWiFi 路由器 Home Assistant 自定义集成，通过路由器本地 Web API 获取实时数据，无需云端。

## ✨ 功能特性

### 📊 路由器传感器 (Sensor)

| 传感器 | 说明 | 默认单位 | 可选单位 |
|--------|------|---------|---------|
| Download Speed | WAN 下载速率 | B/s（显示单位自动） | B/s, kB/s, MB/s, GB/s, KiB/s, MiB/s, GiB/s, bit/s, kbit/s, Mbit/s, Gbit/s |
| Upload Speed | WAN 上传速率 | B/s（显示单位自动） | 同上 |
| Download Total | 累计下载量 | B（显示单位自动） | B, kB, MB, GB, TB, KiB, MiB, GiB, TiB, bit, kbit, Mbit, Gbit |
| Upload Total | 累计上传量 | B（显示单位自动） | 同上 |
| Online Devices | 在线设备数 | devices | (固定) |
| CPU Load | CPU 负载 | % | (固定) |
| Memory Usage | 内存使用率 | % | (固定) |
| Temperature | 路由器温度 | °C | (固定) |
| Speed TOP5 | 网速最快的前 5 个设备 | (无单位，原始 B/s) | (固定) |
| Polling Mode | 自适应轮询当前模式（诊断实体） | (无单位) | (固定) |

**单位说明**（v1.7.0 起）：
- 传感器的**原生值始终是原始字节**（`B/s` / `B`），长期统计记录的也是原始字节，
  所以切换显示单位不会丢历史、也不会重建实体
- 「自动」= 按数值自动选择易读的显示单位；也可固定为某个单位（如 MB/s、GB）
- **单位制式**可按「实时网速」与「累计流量」分别设置为「字节」或「比特」
- 单位同时支持 1000 进制（SI：kB/MB/GB）和 1024 进制（IEC：KiB/MiB/GiB）
- `raw_b` 属性始终保留原始字节数值，方便模板/自动化使用
- `human_readable` 属性提供友好字符串（如 "2.45 MB/s"），`display_unit` 属性给出当前建议显示单位

### 📱 设备追踪 (Device Tracker)

- 每个连接设备自动创建 `device_tracker` 实体
- 在线/离线状态实时检测（`home` / `not_home`）
- **单设备速率数据**：
  - `upload_speed` / `download_speed`：实时上传/下载速率
  - `upload_total` / `download_total`：累计流量
  - `max_upload_speed` / `max_download_speed`：峰值速率
- 信号强度、频道、OUI 等额外信息

### 📶 设备传感器 (Per-Device Sensor)

在集成配置中手动选择需要监控的设备，为每个选中设备自动创建 **4 个独立传感器**：

| 传感器 | 说明 | 默认单位 | 可选单位 |
|--------|------|---------|---------|
| {设备名} Download Speed | 设备下载速率 | B/s | 同路由器速度单位 |
| {设备名} Upload Speed | 设备上传速率 | B/s | 同路由器速度单位 |
| {设备名} Download Total | 设备累计下载量 | B | 同路由器总量单位 |
| {设备名} Upload Total | 设备累计上传量 | B | 同路由器总量单位 |

**与 device_tracker 的区别**：
- `device_tracker` 的速率数据是属性（attribute），**不记录历史**，无法在图表中展示
- `device传感器` 是独立传感器实体，**支持历史记录**，可直接用于 mini-graph-card 等图表卡片

**特性**：
- 新建条目时可选择设备，也可跳过稍后配置
- 已离线但之前选中的设备标注 `[离线]`，方便重新选中
- 取消勾选的设备，其传感器实体在重载后自动清理

### 🔐 加密算法自动检测

MiWiFi 路由器登录密码的哈希算法因固件版本不同而异：
- **新固件**（如 BE5000）：使用 SHA256+SHA256
- **老固件**（如 AX3600、AC2100、AX9000）：使用 SHA1+SHA1

本集成在登录前自动读取路由器 `init_info` 接口中的 `newEncryptMode` 字段判断加密方式，无需用户手动选择：
- `newEncryptMode=1` → 自动使用 SHA256
- 字段不存在或其他值 → 自动使用 SHA1
- 接口不可访问 → 默认使用 SHA1，登录失败自动切换到另一种算法重试

如果自动检测后登录仍然失败，可以在配置里手动指定 SHA1 或 SHA256 跳过自动检测。

### ⚡ 性能优化

| 优化策略 | 说明 | 效果 |
|---------|------|------|
| **分层轮询** | 实时数据 10s + 设备列表 30s + 静态信息 5min | 请求量减少 60%+ |
| **自适应轮询**（v1.7.0） | 空闲（WAN 流量≈0 且设备数稳定）时自动延长实时轮询间隔，流量突增/设备上下线时临时缩短 | 无人使用网络时请求量再降 ~80% |
| **智能触发** | 在线设备数变化时立即轮询设备列表 | 离线检测延迟 < 10秒 |
| **stok 缓存** | 登录 token 缓存 10 分钟 | 减少认证开销 |
| **HTTP Keep-Alive** | aiohttp 连接池复用 TCP 连接 | 每次节省 ~50ms |

#### 自适应轮询详解（v1.7.0）

实时数据（tier 1）不再固定按 `scan_interval` 轮询，而是根据每次轮询已经拿到的
两个信号动态调整：**WAN 上下行速率之和**与**已知设备的 MAC 集合**。

| 模式 | 进入条件 | 实时轮询间隔 |
|------|---------|-------------|
| `active` | 速率 ≥ 「进入活跃模式阈值」（默认 32 KB/s），或设备上下线 | `active_scan_interval`（默认 5s，最小 5s），并在最后一次事件后保持 60s |
| `normal` | 默认 | `scan_interval`（默认 10s） |
| `idle` | 连续 6 次采样速率 ≤ 「空闲判定阈值」（默认 1 KB/s）**且** 设备集合稳定 ≥ 5 分钟 | `idle_scan_interval`（默认 60s，最小 5s） |

防抖动设计：

- 升级到 `active` 立即生效（保证灵敏度）；降级（`active`→`normal`/`idle`）必须
  满足 15s 最短驻留，避免在阈值附近来回抖动；
- 设备上下线在任何模式下都会立即触发设备列表轮询，离线检测不受影响；
- `idle` 模式下设备列表（tier 2）同步退避到 `max(device_scan_interval, idle_scan_interval)`；
- 所有间隔都被夹取到 `[5, 300]` 秒，即使选项填了异常值也不会产生密集请求；
- 关闭 `adaptive_polling` 后行为与旧版固定间隔完全一致。

新增诊断实体 `sensor.miwifi_router_polling_mode`：状态为当前模式
（`active` / `normal` / `idle`），属性给出当前 `interval` 与三个边界值、
`reason`（进入该模式的原因，如 `burst` / `device_event` / `idle_streak` /
`min_dwell`）、`idle_streak`、`transitions`，便于确认自适应是否按预期工作。

### 💱 显示单位与长期统计（v1.7.0）

- 传感器的 **原生单位永远是原始字节**（速率 `B/s`、流量 `B`），写入 HA 的
  长期统计（statistics）也始终是原始字节值。**修改显示单位不再删除/重建实体，
  状态历史与统计都不再丢失**，实体的 `entity_id` 与 `unique_id` 保持不变。
- 显示由 Home Assistant 完成：传感器声明 `device_class`（`data_rate` /
  `data_size`）并把用户选择的单位作为 `suggested_unit_of_measurement`，
  HA 负责换算与显示；你也可以在单个实体的设置里手动指定显示单位，
  HA 会自动换算全部历史数据。
- 由于 HA 只会把"首次见到的单位"记进实体注册表且不再刷新，集成会在实体加载时
  以及自动缩放切换单位时，把当前应显示的单位同步写入实体注册表
  （`sensor.private.suggested_unit_of_measurement`）——这是纯显示层操作，
  不会重建实体、不会影响状态历史与长期统计；你在单个实体里手选的单位仍然优先。
- **单位制式**：实时网速与累计流量**各自独立**配置——`speed_unit_mode` /
  `total_unit_mode`，均可选「字节」（B/s、MB/s、GB…）或「比特」
  （bit/s、Mbit/s、Gbit…）。切换制式只改变显示，不影响数据，因此可以自由组合，
  例如「网速看 Mbit/s、累计流量看 GB」。
- **实时速率自动适配**：`speed_unit = auto`（默认）时，速率传感器会在所选制式内
  根据最近观测到的流量自动选择易读单位（例如 40 kB/s 显示为 `kB/s`、5 MB/s 显示为
  `MB/s`；比特制式下显示 `kbit/s`、`Mbit/s`），升档立即生效、降档带 60s 驻留
  避免来回跳变。
- **累计流量自动适配**：`total_unit = auto` 时按首个非零量级挑选一次稳定单位
  （≥1 GB → GB，≥1 MB → MB，…）后不再变动，避免 `total_increasing` 统计抖动。
- 每个字节类传感器仍保留 `raw_b`（原始字节数，int）与 `human_readable`
  （按当前制式自动缩放的字符串）属性，并新增 `display_unit`（当前建议显示单位）。
- 网速 TOP5 传感器刻意保持无单位（其历史统计的 `unit_class` 为 `unitless`，
  改成 `B/s` 会触发不兼容的单位类变更），改由 `display_value` + `display_unit`
  属性提供可读数值。

### 🔌 路由器控制 (Button)

集成会自动创建一个**重启路由器**按钮实体：

| 按钮 | 说明 | 实体 ID |
|------|------|---------|
| 重启路由器 | 点击后发送重启命令到路由器 | `button.miwifi_router_reboot` |

- 点击按钮即可重启路由器
- 自动使用现有的 stok 认证机制（过期会自动重新登录）
- 重启后路由器需要 1-2 分钟恢复，期间传感器会显示不可用，恢复后自动重新连接
- 配合 HA 自动化可实现"断网自动重启路由器"（见使用示例）

### 🌡️ 温度传感器

路由器温度传感器读取 `/api/misystem/status` 的 `temperature` 字段：
- 温度 > 0：正常显示温度（°C）
- 温度 = 0 或缺失：显示 `unknown`（路由器没有温度传感器，API 文档："若没有温度传感器则为0"）
- BE5000 等无温度传感器的路由器会显示 `unknown`
- AX3600 等有温度传感器的路由器会显示实际温度

### 📶 网速 TOP5 传感器

`sensor.miwifi_router_top5_speeds` 实时显示当前网络中速率最快的 5 个设备：
- **state**：TOP1 设备的总速率（下载+上传，B/s）
- **top5 属性**：TOP5 设备列表，每项包含 name/mac/downspeed/upspeed/total_speed 及 human_readable 版本
- **top5_human 属性**：格式化字符串列表，方便直接展示
- **raw_b 属性**：TOP1 设备总速率原始字节数
- **human_readable 属性**：TOP1 设备总速率友好字符串（按当前单位制式自动缩放）
- **display_value / display_unit 属性**（v1.7.0）：可读数值与单位，例如 `339.9` / `kB/s`（比特制式下为 `2.72` / `Mbit/s`）
- > 该实体的 state 刻意保持为无单位的原始字节/秒（历史统计的 `unit_class` 为
  > `unitless`，改成 `B/s` 会触发不兼容的单位类变更），需要可读数值请使用
  > `display_value` + `display_unit` 或 `human_readable`。
- 配合 Markdown 卡片可展示网速排行榜（见使用示例）

### 📱 设备追踪名称

每个设备追踪器（device_tracker）只显示设备自身名称（如 "Redmi-Note-8-Pro"），不带路由器前缀。每个设备作为独立的 HA 设备条目，通过 `via_device` 关联到路由器。

## 📋 支持型号

所有运行 MiWiFi 固件的小米路由器，包括但不限于：

| 型号 | 平台 | 状态 |
|------|------|------|
| Xiaomi BE5000 | RD18 | ✅ 已验证 |
| Xiaomi BE3600 | RD09 | 🔶 理论兼容 |
| Xiaomi AX9000 | RA69 | 🔶 理论兼容 |
| Xiaomi AX6000 | RA67 | 🔶 理论兼容 |
| Xiaomi AX3600 | RA70 | 🔶 理论兼容 |
| Xiaomi AX3000T | RB01 | 🔶 理论兼容 |
| Redmi AX6 | RA69 | 🔶 理论兼容 |
| Redmi AX5 | RB03 | 🔶 理论兼容 |
| Redmi AC2100 | RM2100 | 🔶 理论兼容 |

> - ✅ **已验证**：经实际设备测试确认可用
> - 🔶 **理论兼容**：基于相同 MiWiFi 固件 API 推断兼容，未经实际设备验证
>
> 其他运行 MiWiFi 固件的路由器理论上均兼容，欢迎反馈测试结果，验证后将升级为 ✅。

### 如何判断我的路由器是否支持？

只需在浏览器中直接访问以下两个地址之一（将 `192.168.31.1` 替换为你的路由器 IP）。**新固件和老固件使用不同的 URL 路径**，本集成会自动尝试这两个地址：

**地址 1（新固件，2023 年 5 月后机型）：**
```
http://192.168.31.1/api/xqsystem/init_info
```

**地址 2（老固件，AX3600/AC2100/AX9000 等）：**
```
http://192.168.31.1/cgi-bin/luci/api/xqsystem/init_info
```

判断方法：

- **任一地址显示 JSON 数据**，包含路由器型号、固件版本等信息，说明完全支持：

```json
// 新固件示例 (BE5000)
{"hardware":{"platform":"RD18","version":"1.0.53","displayName":"Xiaomi BE5000"}, "newEncryptMode":1, ...}

// 老固件示例 (AX3600, 没有 newEncryptMode 字段或字段为 0)
{"romversion":"1.0.168","countrycode":"CN","code":0,"model":"xiaomi.router.ra70","hardware":"RA70",...}
```

- **如果两个地址都返回 404 或 nginx 默认错误页**，说明路由器固件版本过老或固件分支不同，本集成可能无法使用

- **如何确认你的路由器用哪种加密算法**：看返回 JSON 里有没有 `newEncryptMode` 字段
  - `newEncryptMode=1` → 新固件，使用 SHA256（无需手动选，集成会自动检测）
  - `newEncryptMode` 字段缺失、为 0 或其他值 → 老固件，使用 SHA1（无需手动选，集成会自动检测）
  - 两个地址都打不开 → 集成默认用 SHA1，登录失败会自动切换到 SHA256 重试

> 💡 这些接口**都不需要登录**即可访问。集成会自动按"地址 1 → 地址 2"的顺序尝试，并用返回结果决定登录算法，所以你**不需要手动选择**算法 —— 默认的"自动检测"模式已经覆盖所有情况。
>
> 如果自动检测后登录仍然失败，可以在集成配置里手动选择"强制 SHA1"或"强制 SHA256"作为兜底。

## 📥 安装

### 方法 1：HACS（推荐）

1. 在 HACS 中添加自定义仓库：
   - 打开 HACS → 集成 → 右上角菜单 → 自定义仓库
   - 仓库 URL：`https://github.com/tiejiang29/miwifi_router`
   - 类别：集成
2. 搜索 "MiWiFi Router" 并点击安装
3. 重启 Home Assistant

### 方法 2：手动安装

1. 下载 `custom_components/miwifi_router/` 目录
2. 复制到 HA 配置目录的 `custom_components/` 下
```bash
cp -r custom_components/miwifi_router /config/custom_components/
```
3. 重启 Home Assistant

## ⚙️ 配置

### 新建条目

通过 UI 配置流程完成，**无需编辑 YAML**：

1. 进入 **设置 → 设备与服务 → 添加集成**
2. 搜索 "MiWiFi Router"
3. 填写连接信息和选项：
   - **路由器 IP 地址**：默认 `192.168.31.1`
   - **路由器管理密码**：MiWiFi 管理界面登录密码
   - **实时数据轮询间隔**：默认 10 秒（自适应轮询 `normal` 模式下的间隔，最小 5 秒）
   - **设备列表轮询间隔**：默认 30 秒（最小 5 秒）
   - **自适应轮询**：默认开启；关闭后行为与旧版固定间隔完全一致
   - **空闲轮询间隔**：默认 60 秒（空闲模式下的实时数据间隔）
   - **流量突增轮询间隔**：默认 5 秒（检测到突增/设备上下线时的间隔）
   - **空闲判定阈值**：默认 1 KB/s，速率低于该值算空闲
   - **进入活跃模式阈值**：默认 32 KB/s，速率高于该值立即加快轮询并在 60 秒内保持
   - **密码哈希算法**：默认"自动检测"，登录失败可手动选 SHA1/SHA256
   - **实时网速单位制式**：字节（B/s、MB/s…）或比特（bit/s、Mbit/s…）
   - **实时网速传感器单位**：默认"自动"（按数值自动选择易读单位），也可固定为 B/s、kB/s、MB/s、GB/s、Mbit/s 等
   - **累计流量传感器单位**：默认"自动"（按数值自动选择易读单位），也可固定为 B、kB、MB、GB、TB、Gbit 等
4. 连接成功后，进入 **选择需添加传感器的设备** 步骤：
   - 勾选需要监控的设备（可跳过，稍后添加）
   - 每个选中设备将创建 4 个独立传感器
5. 提交完成

> ℹ️ 网速/流量单位是**显示单位**，随时可在配置里修改：不会重建实体，也不会丢失历史数据与长期统计。

### 修改配置

1. 进入 **设置 → 设备与服务 → MiWiFi Router → ⚙️ 配置**
2. 可修改以下选项：
   - **实时数据/设备列表轮询间隔**
   - **自适应轮询 / 空闲轮询间隔 / 流量突增轮询间隔 / 空闲判定阈值 / 进入活跃模式阈值**
   - **需添加传感器的设备**：勾选/取消设备
   - **密码哈希算法**：切换 SHA1/SHA256/自动检测
   - **实时网速单位制式** / **累计流量单位制式**：字节 ↔ 比特（各自独立，只改变显示）
   - **实时网速传感器单位**：切换显示单位（或自动）
   - **累计流量传感器单位**：切换显示单位（或自动）
3. 提交后集成自动重载，配置立即生效

### 修改单位会发生什么？（v1.7.0 起）

改单位**不会**再删除或重建任何实体：

- 传感器上报的值始终是原始字节（`B/s` / `B`），因此长期统计
  （statistics）里始终是原始字节值，`sum` 连续、不会重置；
- 显示单位通过 `suggested_unit_of_measurement` 交给 Home Assistant 换算，
  实体的 `entity_id`、`unique_id`、状态历史全部保持不变；
- 你也可以在**单个实体**的设置里手动指定显示单位，HA 会换算该实体的全部
  历史数据，同样不丢历史；
- 旧版本里的"历史数据会丢失"确认对话框已移除（不再需要）。

> ⚠️ 唯一例外：`sensor.miwifi_router_speed_top5` 刻意保持无单位（它的历史统计
> `unit_class` 是 `unitless`，改成 `B/s` 会触发不兼容的单位类变更），可读数值
> 请使用它的 `display_value` + `display_unit` 属性。

### 单位选择建议

| 场景 | 推荐设置 |
|------|---------|
| 想省心、看可读数值 | 两个制式都=字节，网速单位=自动，流量单位=自动（默认） |
| 习惯按带宽算（如 100 Mbps 家宽） | 网速制式=比特 + 网速单位=自动（显示 Mbit/s），流量制式可仍用字节 |
| 网速用比特、流量用字节 | 实时网速单位制式=比特，累计流量单位制式=字节（各自独立） |
| 想固定显示（如始终 MB/s） | 网速单位=MB/s，流量单位=GB |
| 用于模板精确计算 | 任意显示单位 + `raw_b` 属性（始终是原始字节） |

## 📖 使用示例

### 设备速率图表

使用 mini-graph-card 展示设备实时速率：

```yaml
type: custom:mini-graph-card
entities:
  - sensor.xiaomizhu_lu_you_qi_istoreos_download_speed
  - sensor.xiaomizhu_lu_you_qi_istoreos_upload_speed
name: istoreos 网速
hours_to_show: 1
```

### 在模板中获取原始字节数

无论传感器显示单位是什么，`raw_b` 属性始终保留原始字节数，方便模板/自动化精确计算：

```jinja
{# 获取下载速率的原始字节数 #}
{{ state_attr('sensor.miwifi_router_download_speed', 'raw_b') }}
{# 输出: 2630 (单位 B/s) #}

{# 获取累计下载量的原始字节数 #}
{{ state_attr('sensor.miwifi_router_download_total', 'raw_b') }}
{# 输出: 42662921949 (单位 B) #}

{# 换算成 GB 显示 #}
{{ (state_attr('sensor.miwifi_router_download_total', 'raw_b') / 1073741824) | round(2) }} GiB
{# 输出: 39.73 #}
```

### 在模板中使用 human_readable 友好字符串

```jinja
{{ state_attr('sensor.miwifi_router_download_speed', 'human_readable') }}
{# 输出: "2.63 KB/s" #}

{{ state_attr('sensor.miwifi_router_download_total', 'human_readable') }}
{# 输出: "42.66 GB" #}
```

### 自动化：设备上线通知

```yaml
automation:
  - alias: "手机连接WiFi通知"
    trigger:
      - platform: state
        entity_id: device_tracker.miwifi_router_device_xx_xx_xx_xx_xx_xx
        to: "home"
    action:
      - service: notify.mobile_app
        data:
          title: "设备上线"
          message: "{{ trigger.to_state.attributes.friendly_name }} 已连接WiFi"
```

### 自动化：设备离线检测

```yaml
automation:
  - alias: "设备离线通知"
    trigger:
      - platform: state
        entity_id: device_tracker.miwifi_router_device_xx_xx_xx_xx_xx_xx
        to: "not_home"
        for:
          minutes: 5
    action:
      - service: notify.mobile_app
        data:
          title: "设备离线"
          message: "{{ trigger.from_state.attributes.friendly_name }} 已断开WiFi超过5分钟"
```

### 查看 device_tracker 的速率属性

device_tracker 实体的速率数据是属性，可以直接在模板中读取：

```jinja
{{ state_attr('device_tracker.miwifi_router_device_xx_xx_xx_xx_xx_xx', 'download_speed_human') }}
{# 输出: "2.45 MB/s" #}

{{ state_attr('device_tracker.miwifi_router_device_xx_xx_xx_xx_xx_xx', 'upload_speed_human') }}
{# 输出: "156.00 KB/s" #}
```

### 自动化：断网自动重启路由器

利用重启按钮实现断网自动恢复，适用于 PPPoE 拨号被运营商踢下线的场景。

> ⚠️ **重要：防循环重启保护**
> 如果断网是线路故障（不是拨号 session 过期），重启后仍然断网，会导致自动化反复触发重启。**必须加次数限制**，否则会损坏路由器硬件。下面的示例已包含每日重启次数限制。

#### 第 1 步：创建重启次数计数器

在 HA 的"助手"页面创建一个 `input_number` 实体（设置 → 设备与服务 → 助手 → 创建助手 → 数字）：

- 名称：`今日路由器重启次数`
- 最小值：0
- 最大值：5
- 步长：1
- 初始值：0

或者用 YAML：

```yaml
# configuration.yaml
input_number:
  router_reboot_count_today:
    name: 今日路由器重启次数
    initial: 0
    min: 0
    max: 5
    step: 1
```

#### 第 2 步：配置自动化

**方案 1：用下载速度检测断网**（推荐，无需额外集成）

当下载速率持续 5 分钟接近 0 时，自动重启路由器：

```yaml
automation:
  # 每天凌晨重置重启计数器
  - alias: "重置路由器重启计数器"
    trigger:
      - platform: time
        at: "00:00:00"
    action:
      - service: input_number.set_value
        target:
          entity_id: input_number.router_reboot_count_today
        data:
          value: 0

  # 断网自动重启（带次数限制 + 冷却时间）
  - alias: "断网自动重启路由器"
    mode: single
    max_exceeded: silent
    trigger:
      - platform: numeric_state
        entity_id: sensor.miwifi_router_download_speed
        below: 1
        for:
          minutes: 5
    condition:
      # 每天最多重启 3 次
      - condition: numeric_state
        entity_id: input_number.router_reboot_count_today
        below: 3
    action:
      - service: button.press
        target:
          entity_id: button.miwifi_router_reboot
      - service: input_number.increment
        target:
          entity_id: input_number.router_reboot_count_today
      - delay: "00:10:00"  # 重启后等 10 分钟再允许下一次触发
```

**方案 2：用 Ping 集成检测外网连通性**（更准确）

先在 `configuration.yaml` 配置 Ping 集成检测外网 IP：

```yaml
binary_sensor:
  - platform: ping
    host: 8.8.8.8
    name: "外网连通性"
    count: 3
    scan_interval: 30
```

然后配置自动化（同样带次数限制）：

```yaml
automation:
  - alias: "重置路由器重启计数器"
    trigger:
      - platform: time
        at: "00:00:00"
    action:
      - service: input_number.set_value
        target:
          entity_id: input_number.router_reboot_count_today
        data:
          value: 0

  - alias: "断网自动重启路由器"
    mode: single
    max_exceeded: silent
    trigger:
      - platform: state
        entity_id: binary_sensor.wai_wang_lian_tong_xing  # Ping 实体名
        to: "off"
        for:
          minutes: 3
    condition:
      - condition: numeric_state
        entity_id: input_number.router_reboot_count_today
        below: 3
    action:
      - service: button.press
        target:
          entity_id: button.miwifi_router_reboot
      - service: input_number.increment
        target:
          entity_id: input_number.router_reboot_count_today
      - delay: "00:10:00"
```

#### 保护机制说明

| 保护机制 | 作用 |
|---------|------|
| `input_number` 计数器 | 每天最多重启 3 次，防止线路故障导致循环重启 |
| 每日凌晨重置 | 新的一天重新计数 |
| `delay: 10分钟` | 重启后给路由器恢复时间，期间不重复触发 |
| `mode: single` | 自动化执行期间不重复触发 |
| `max_exceeded: silent` | 被跳过的触发不记录日志，避免日志爆炸 |

> 💡 可在 HA 仪表盘上加一张卡片显示"今日路由器重启次数"，方便监控。如果某天重启次数达到 3 次，说明大概率是线路问题，需要人工排查。

## ❓ 常见问题

### Q: 出现 invalid-auth 错误？

可能的原因和排查步骤：

1. **确认密码无误**：在浏览器中访问 `http://路由器IP` 并用相同密码登录，验证密码本身正确。

2. **手动指定算法**：在配置流程的"密码哈希算法"选项中手动选择：
   - 老固件（AX3600、AC2100、AX9000、Redmi AX6/AX5、AX3000T 等）→ 强制 SHA1
   - 新固件（BE5000、BE3600、小米路由器 7000 等，2023 年 5 月后）→ 强制 SHA256

3. **检查 init_info 接口**：在浏览器中访问以下两个地址之一，查看返回的 `newEncryptMode` 字段：
   - `http://路由器IP/api/xqsystem/init_info` （新固件路径）
   - `http://路由器IP/cgi-bin/luci/api/xqsystem/init_info` （老固件路径）

   `newEncryptMode=1` 表示新固件 SHA256，缺失或其它值表示老固件 SHA1。

4. **检查路由器是否屏蔽了 HA 主机**：如果连续多次登录失败，路由器可能临时屏蔽 HA 主机 IP（防爆破机制）。重启路由器或等待几小时后重试。

5. **反馈日志**：如果以上方法均无效，请在 [GitHub Issues](https://github.com/tiejiang29/miwifi_router/issues) 中提交 HA 日志。先在 `configuration.yaml` 里开启 debug 日志：
   ```yaml
   logger:
     logs:
       custom_components.miwifi_router: debug
   ```
   重启 HA，复现问题，然后把日志里搜 `[DEBUG]` 的内容贴出来。

### Q: 传感器显示"未知"？
检查路由器 IP 和密码是否正确，确保 HA 和路由器在同一局域网。可在配置中点击"验证"测试连接。

### Q: 实时数据轮询间隔和设备列表轮询间隔有什么区别？
- **实时数据轮询间隔**（`scan_interval`）：控制 WAN 上下行速率、累计流量、CPU 负载、内存使用率等路由器自身传感器的刷新频率。这些数据变化快，默认 10 秒即可获得平滑的速率曲线。
- **设备列表轮询间隔**（`device_scan_interval`）：控制设备在线状态、设备速率属性、设备传感器的刷新频率。设备列表 API 响应较重（包含所有连接设备的详细信息），默认 30 秒可以在及时检测上下线的同时减少对路由器的请求压力。

简单来说：想看更流畅的网速曲线就调小 `scan_interval`；想更快发现设备上下线就调小 `device_scan_interval`，但不要设得太小以免增加路由器负担。

v1.7.0 起这两个间隔都由**自适应轮询**动态调节：空闲时自动拉长（实时数据最长 60 秒、
设备列表同步退避），流量突增或设备上下线时自动缩短（最快 5 秒）。你设置的
`scan_interval` 就是 `normal` 模式下的间隔，`自适应轮询` 关闭后即为固定间隔。
当前模式与间隔可直接看 `sensor.miwifi_router_polling_mode`。

### Q: 和 xiaomi_home / hass-xiaomi-miot 有什么区别？
那两个集成走 MIoT 协议，但路由器固件不响应属性读取请求，所以传感器全部显示"未知"。本集成走路由器本地 Web API，直接获取实时数据。

### Q: 会影响路由器性能吗？
不会。HTTP Keep-Alive 复用连接，分层轮询减少请求量，v1.7.0 起还有自适应轮询：
网络空闲时实时轮询最长 60 秒一次。路由器管理界面每 2 秒轮询，本集成的负载远低于网页管理。

### Q: device_tracker 的速率数据和设备传感器有什么区别？
`device_tracker` 的速率是属性（attribute），HA 不记录属性历史，无法直接画图。设备传感器是独立实体，支持历史记录，可直接用于图表。如果需要在仪表盘中展示设备速率曲线，请选中对应设备创建传感器。

### Q: 修改单位后界面还是显示老单位 / 标题显示"高级选项" / 字段标签显示英文？
这是 HA 的 translations 缓存问题。translations 在 HA 启动时加载，重新加载集成不会重新加载。请按以下步骤操作：

1. **完全重启 Home Assistant**（不是重新加载集成）
   - 设置 → 系统 → 右上角电源图标 → 重新启动
2. **硬刷新浏览器**
   - Windows/Linux：`Ctrl + Shift + R`
   - macOS：`Cmd + Shift + R`
3. **检查 HA 语言设置**
   - 设置 → 个人资料 → 语言 → 必须是"简体中文"才会加载中文翻译

### Q: 修改单位后历史数据丢失了，能恢复吗？
**v1.7.0 起不会再丢失**。传感器原生值始终是原始字节，改单位只改变显示方式：
不会重建实体、不会丢失状态历史，长期统计（statistics）也保持连续。所以这个
问题在新版本中已经不存在了；旧的「确认丢失历史」对话框也一并移除。

如果你是从 v1.6.3 及更早版本升级、且过去改过单位，那么当时被删除重建的那批
实体的状态历史确实无法找回（数据在删除时已经孤悬），但长期统计仍保留在数据库里，
升级后 `sensor.miwifi_router_download_total` 等实体的统计 `sum` 会继续累加。

### Q: 单位的「自动」和「字节/比特」制式分别是什么意思？
- **自动**：显示单位由集成根据最近的数值自动选择，保证数字落在易读区间
  （例如 40 KB/s、5 MB/s；累计流量则按首个非零量级固定一次，避免统计抖动）。
- **显式单位**（如 MB/s、GB）：始终以该单位显示，不做自动缩放。
- **单位制式**（字节 / 比特）：只影响显示家族。比特制式下同样的数据会显示为
  bit/s、Mbit/s、Gbit 等（1 字节 = 8 比特），底层数据与统计完全不变。
- 也可以在**单个实体**的 HA 设置里手动指定显示单位，优先级高于集成建议值。

## 📁 文件结构

```
custom_components/miwifi_router/
├── __init__.py          # 集成入口（读取选项、创建协调器；已不再删除/重建传感器实体）
├── adaptive.py          # 自适应轮询状态机（纯标准库，可脱离 HA 测试）
├── api.py               # 路由器 API 客户端（登录、加密算法自动检测、stok缓存、Keep-Alive、重启）
├── button.py            # 按钮平台（重启路由器）
├── config_flow.py       # UI 配置流程（设备选择、轮询、速率/流量单位制式与显示单位）
├── const.py             # 常量定义（自适应轮询参数、单位选项与换算因子）
├── coordinator.py       # 数据更新协调器（分层轮询 + 自适应调度、TOP5 速率计算）
├── device_tracker.py    # 设备追踪平台（在线检测+单设备速率属性）
├── diagnostics.py       # 诊断导出（含自适应轮询状态，密码已脱敏）
├── manifest.json        # 集成清单
├── sensor.py            # 传感器平台（原始字节 native + HA 显示换算、自动缩放、TOP5、温度、轮询模式）
├── units.py             # 单位引擎（字节/比特两族换算、自动缩放、可读字符串；纯标准库）
├── strings.json         # 翻译源文件（参考用）
└── translations/        # 实际加载的翻译文件
    ├── en.json          # 英文
    └── zh-Hans.json     # 简体中文
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📝 更新日志

### v1.8.0
- **单位制式按速率与累计流量独立设置**：新增 `speed_unit_mode` / `total_unit_mode`
  两个选项，可以「网速用比特（Mbit/s）、流量用字节（GB）」这样自由组合；v1.7.0 的
  单一 `unit_mode` 选项会在加载时自动迁移到这两个键，原有设置不丢失
- **自适应轮询的流量阈值可在设置页面配置**：新增「空闲判定阈值（KB/s，默认 1）」与
  「进入活跃模式阈值（KB/s，默认 32）」两个选项，并暴露在
  `sensor.miwifi_router_polling_mode` 的 `idle_traffic_bps` / `active_traffic_bps` 属性
- **轮询间隔输入改为显式校验（最小 5 秒）**：填 2 秒会在表单直接报错，而不是被静默改成 5 秒
- 自动缩放说明补充：升档立即生效、降档带 60s 驻留；累计流量按首个非零量级固定
  一次，避免 `total_increasing` 统计抖动

### v1.7.0
- **自适应轮询**：新增 `adaptive.py` 状态机，实时数据轮询间隔随网络负载自动调节
  - 空闲（WAN 流量≈0 且设备数稳定）→ `idle`，间隔拉长到 `idle_scan_interval`（默认 60s）
  - 流量突增（≥32 KB/s）或设备上下线 → `active`，间隔缩短到 `active_scan_interval`（默认 5s），并保持 60s
  - 升级立即生效、降级需 15s 最短驻留，避免抖动；间隔统一夹取到 `[5, 300]` 秒
  - 空闲时设备列表（tier 2）同步退避；设备上下线在任何模式下都立即刷新设备列表
  - 新增选项 `adaptive_polling` / `idle_scan_interval` / `active_scan_interval`，关闭后与旧版固定间隔一致
  - 新增诊断实体 `sensor.miwifi_router_polling_mode`（状态=模式，属性含当前间隔与原因）
  - 新增 `diagnostics.py`，可在集成页面下载诊断信息（含自适应状态，密码已脱敏）
- **显示单位与长期统计保命**：改单位不再重建实体、不再丢失历史
  - 传感器原生单位固定为原始字节（`B/s` / `B`），长期统计始终记录原始字节，`sum` 连续
  - 通过 `device_class`（`data_rate` / `data_size`）+ `suggested_unit_of_measurement` 交给 HA 换算显示
  - 新增单位制式选项：**字节**（B/s、MB/s、GB…）或**比特**（bit/s、Mbit/s、Gbit…）
  - 「自动」单位改为按数值自动缩放（速率带滞回与 300s 最小切换间隔；累计流量只固定一次，避免统计抖动）
  - 每个字节类传感器保留 `raw_b` / `human_readable`，新增 `display_unit` 属性
  - 移除「修改单位会丢失历史」确认步骤；`speed_top5` 保持无单位并新增 `display_value` / `display_unit`
  - 新增 `units.py` 纯标准库单位引擎（可脱离 HA 测试）
  - 修复实机验证发现的两个缺陷：`suggested_unit_of_measurement` 支持性探测方式
    （HA 2026.9 的 `SensorEntityDescription` 不是 dataclass，旧探测恒为假，导致自动
    缩放从未生效）；显示单位被 HA 实体注册表"钉死"导致改配置后不生效（改由集成
    同步注册表项，仍然不重建实体、不丢历史）

### v1.6.3
- 设备传感器（per-device sensor）新增 `mac` 和 `ip` 属性，解决同名/泛用名设备无法辨识实体的问题

### v1.6.2
- 新增路由器温度传感器（`sensor.miwifi_router_temperature`），温度为 0 时显示 unknown

### v1.6.1
- device_tracker 实体名不再带路由器前缀，只显示设备自身名称
- 每个设备作为独立的 HA 设备条目，通过 via_device 关联到路由器

### v1.6.0
- 新增网速 TOP5 传感器（`sensor.miwifi_router_top5_speeds`），实时显示速率最快的 5 个设备
- 支持 Markdown 卡片展示网速排行榜

### v1.5.1
- 修复部分设备速度始终为 0 的问题
- 改用 device_list API 作为设备速度的主要数据源（status 只返回 top-N 设备）
- 修复 device_list 速度数据嵌套在 statistics 对象里读取不到的问题

### v1.5.0
- 新增路由器重启按钮（`button.miwifi_router_reboot`）
- 支持断网自动重启自动化（README 含完整示例 + 防循环重启保护）

### v1.4.2
- 修复 v1.4.1 丢失的单位换算逻辑，speed_unit / total_unit 配置重新生效
- 恢复 raw_b 和 human_readable 属性

### v1.4.1
- 传感器名称改用 translation_key，支持中文显示
- 修复单设备传感器名称翻译

### v1.4.0
- 新增用户可选传感器单位（speed_unit / total_unit）
- 修改单位时弹出确认对话框，警告历史数据丢失
- 完整中文本地化（translations/ 目录）
- 初次添加表单加单位修改提示语

### v1.3.17
- 自定义集成改用 translations/ 目录（HA 规范要求）
- 修复确认步骤崩溃（async_show_form 不接受 description 参数）

### v1.3.14
- 用户自选单位方案（回退 v1.3.11 的 device_class + suggested_unit 方案）

### v1.3.8
- 修复 SHA1 fallback 永不触发的 BUG
- init_info 双 URL 路径检测
- 新增 force_hash_algo 配置项

## ⚖️ 许可证

[MIT License](LICENSE)
