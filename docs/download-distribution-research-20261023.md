# 免代理分发调研（2026-10-23）

用户目标：普通用户不配置外部代理，也能在程序内获取语音资源并完成安装。仅证明代理开启后能下载不满足这一目标。本轮为网上调研，没有接入新平台、上传资源、购买云服务或修改产品代码，也没有干扰用户当前下载。

## 核对到的项目做法

| 项目 | 官方页面实际提供的渠道 | 可借鉴之处 |
| --- | --- | --- |
| GPT-SoVITS | 官方 v2pro 发布页提供 ModelScope 整合包直链、Hugging Face 中国镜像和百度网盘 | 与本项目最接近：完整 AI 整合包可以单独发布在国内分发渠道；无需改变本机稳定推理环境 |
| Dub Genius（2DIPW） | GPT-SoVITS + PySide6 项目，989MB CPU包和2.18GB GPU包均提供 OneDrive、百度网盘 | 整合包与 GitHub 源码分开分发，网盘适合手工下载后离线导入 |
| Cherry Studio | 官网下载页提供夸克网盘入口 | 主下载之外保留面向用户的备用渠道；不等于网盘分享页可直接用于程序内下载 |
| 思源笔记 | 官方下载页指向 release.liuyun.io，并另有百度网盘；历史版本链接 GitHub | 使用独立下载入口并保留备用渠道；仅凭域名不能断言后台是哪家云或国内线路可用性 |

一手来源：

- [GPT-SoVITS 官方 Release](https://github.com/RVC-Boss/GPT-SoVITS/releases/tag/20250606v2pro)
- [GPT-SoVITS ModelScope 整合包仓库](https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/files)
- [Dub Genius 作者仓库](https://github.com/2DIPW/dub_genius)
- [Cherry Studio 官方下载页](https://cherryai.com/download)
- [思源笔记官方下载页](https://b3log.org/siyuan/download.html)

本轮查看的是页面提供的渠道，没有完整下载这些项目的包，未验证所有链接在用户关闭代理后的吞吐或可用性。GPT-SoVITS 发布页的速度描述不能当作 TachiTalk 的真实验收。

## 对 TachiTalk 的建议

1. **成本优先的候选：国内 AI 资源托管。** 先核对 ModelScope 对本项目完整运行环境/模型包的托管规则、配额及公开下载条件，再用自有仓库验证匿名直链和断点续传。官方 GPT-SoVITS 的整合包分发方式可作技术参考，不能据此承诺免费、无限配额或永久可用。
2. **生产分发更可控的候选：国内区域 COS/OSS，按需加 CDN。** 云对象存储有标准 HTTP 下载及范围请求能力；腾讯云官方 GET Object 文档明确给出 Range、HTTP206 和 Content-Range。开发者承担存储、请求和下载流量费用；具体价格须按区域/套餐报价。
3. **手工兜底：网盘 + 已有离线导入。** 不能用登录页、提取码或第三方直链解析替代正式的程序内下载接口。

参考：[腾讯云 GET Object](https://intl.cloud.tencent.com/zh/document/product/436/7753)、[阿里云 OSS 流量费用](https://help.aliyun.com/zh/oss/traffic-fees)、[ModelScope 下载实现](https://github.com/modelscope/modelscope/blob/master/modelscope/hub/file_download.py)。

容量估算：现有语音压缩包6,219,221,474字节，约5.79GiB；100次完整下载约622GB十进制出网流量（不计重试），故云服务主要要评估下载流量，不能只看约6GB存储。

## 接入时必须闭合的流程

- 国内优先源同时提供版本/签名清单和四个原字节分卷，不能只迁移大文件而仍依赖 GitHub 才能检查资源。
- GitHub 保留为备用/公开归档；公共 GitHub 代理作为额外候选，不作为免代理目标的验收依据。
- 本项目清单签名覆盖下载地址，现有地址校验只允许官方 GitHub Release URL。不能直接改已签名清单中的 URL，也不能全面放开任意主机重定向。可设计经过明确主机/仓库约束的镜像映射，继续用原签名和分卷 SHA256 验证同字节副本；具体方案需实施前确定。
- 不改变 GPT-SoVITS v2ProPlus / PyTorch2.7.1 / CUDA12.8；不需为了迁移分发渠道重新压缩语音环境。
- 验收使用关闭外部代理的普通网络，验证检查清单、首字节时间、可见进度、暂停/取消、HTTP206续传、整个包哈希和安装结果。只能据实际覆盖的网络报告，不能承诺任意网络永远可达。

当前结论：建议优先评估 ModelScope 作为国内语音主源；若平台条件不满足或需要更可控的服务，采用国内 COS/OSS 分发。是否采用及费用尚未确定，免代理渠道尚未实现。
