# 第三方组件与许可（NOTICE）

本项目源码以 [MIT](LICENSE) 许可发布。
但**分发包**里内嵌了第三方组件，它们各自有许可约束，一并说明如下。

## 1. NapCat（QQ 协议端）

```
项目      NapNeko/NapCatQQ
版本      4.18.42（NapCat.Shell.zip）
sha256    02e5ff0f79916c1e04c81c1b4590056406fb4293f1f1300c955e71fd08b2829d
许可      Limited Redistribution License（限制性再分发许可）
         · 允许原样随附分发
         · 必须附许可全文与来源声明
         · 仅限非商业用途
位置      apk_src_v2/napcat_assets/NapCat-LICENSE.txt
          apk_src_v2/napcat_assets/NOTICE.txt
```

**因此：整个 APK 的分发必须保持非商业。** 如需商用，请自行取得 NapCat 作者的书面授权。

## 2. Python 运行时（Termux 构建）

```
来源      termux/termux-packages（官方仓库构建产物）
许可      各包按自身许可（多数为 PSF / MIT / BSD / LGPL）
位置      apk_src_v2/assets/runtime.zip
```

## 3. Ubuntu Base 根文件系统

```
来源      ubuntu-base-22.04.5-base-arm64.tar.gz（官方）
许可      Ubuntu 组件各自许可（GPL/LGPL 等），随包保留原许可文件
位置      运行时下载（容器创建时），不随 APK 分发
```

## 4. proot

```
项目      termux/proot
许可      GPL-2.0
位置      apk_src_v2/assets/runtime.zip 内的 usr/bin/proot
说明      GPL 组件以独立进程方式调用，不与我们的代码链接
```

## 5. 不包含的部分

```
✗ 腾讯 QQ 客户端 —— 不打包、不下载、不代下
   用户必须自行从官方渠道获取并自行承担风险
✗ NapCat 的 WebUI 前端以外的闭源组件（如有）—— 不在本项目分发范围
```

## 7. 签名密钥

`
文件      apk_src_v2/debug.keystore（2.6 KB，随仓库公开）
密码      android
指纹      a886674ee71b265062a53175f3d33c3fa3435c65b6e12257776cc45751d16216
用途      让 CI 与本地构建产出同一签名，保证能覆盖升级
说明      这是自签名调试密钥，不是商店密钥；公开意味着任何人都能签同名包
          若将来上架商店或正式发布，需更换密钥并移出仓库
`

## 6. 我们的合规承诺

```
· 不修改 NapCat 源码，原样保留（含许可文件）
· 不在 Release 里放 QQ 安装包
· 不提供任何"破解登录""绕过风控"的能力
· 项目非商业，与腾讯、NapCat 官方均无隶属关系
```

如你是权利人并认为本仓库有不当之处，请开 issue，我们会在核实后立即处理。
