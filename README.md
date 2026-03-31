# TaxShield 税盾

> 开源税表脱敏工具 — 在本地对税表进行 PII 脱敏，保护隐私后再提交第三方审查

## 项目简介

TaxShield 是一个完全在用户设备上运行的命令行工具，用于对美国联邦税表（1040 及相关附表、W-2、1099 等）进行个人身份信息（PII）脱敏处理。

**核心原则：**
- 完全离线运行，不联网
- 开源代码，用户可审查
- 用户的原始文件永远不离开用户设备

## 快速开始

```bash
# 脱敏单个文件
taxshield redact "Luna Wang 25.pdf"

# 脱敏整个目录
taxshield redact ./tax_documents/

# 查看帮助
taxshield --help
```

## 输入输出

**输入：** 单个文件或目录（支持 PDF 和图片 JPG/PNG）

**输出：** 输入路径下的 `redacted/` 子目录

```
tax_documents/                        # 输入目录
├── Luna Wang 25.pdf                  # 原始文件
├── W2_photo.jpg
├── 1099-DIV.png
└── redacted/                         # 输出子目录（自动创建）
    ├── Luna Wang 25_redacted.pdf     # 脱敏后的 PDF
    ├── W2_photo_redacted.pdf         # 图片统一转 PDF
    ├── 1099-DIV_redacted.pdf
    ├── redaction_map.txt             # 映射表（用户查看）
    └── redaction_map.csv             # 映射表（程序使用）
```

## 许可证

MIT License — 开源，自由使用
