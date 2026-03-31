# TaxShield 税盾 — 设计文档

> 版本：v0.1
> 状态：设计阶段
> 最后更新：2026-03-30

---

## 一、产品定位

### 是什么
一个在用户设备上本地运行的命令行工具，对美国联邦税表进行 PII（个人身份信息）脱敏处理。

### 不是什么
- 不是通用的文档脱敏工具（只针对美国税表）
- 不是云服务（完全离线运行）
- 不做任何税务分析（只做脱敏）

### 为什么需要
用户在使用 AI 税务审查服务（如 TaxAuditor）时，需要将税表提交给第三方。税表包含极敏感的 PII（SSN、银行账号等），用户不应该把这些信息暴露给任何第三方。TaxShield 在本地完成脱敏，确保用户提交的文件中不含真实 PII。

### 信任模型
- 工具完全开源，用户或安全专家可审查代码
- 完全离线运行，用户可在断网状态下使用
- 用户可用网络监控工具验证无数据外传

---

## 二、输入输出规格

### 输入

| 项目 | 说明 |
|---|---|
| 输入方式 | 单个文件路径 或 目录路径 |
| 支持格式 | PDF、JPG、PNG |
| 文件类型 | 美国联邦税表（1040 及附表、W-2、1099 系列、1098、Form 8949、Form 8615 等） |

### 输出

| 项目 | 说明 |
|---|---|
| 输出位置 | 输入路径下自动创建 `redacted/` 子目录 |
| 输出格式 | 全部为 PDF（图片输入会转换为 PDF）|
| 文件命名 | 原文件名 + `_redacted` 后缀 |
| 映射表 | `redaction_map.txt`（用户查看）+ `redaction_map.csv`（程序使用） |

### 输出目录结构示例

```
tax_documents/
├── Luna Wang 25.pdf                  # 原始 PDF
├── W2_photo.jpg                      # 原始图片
├── 1099-DIV.png                      # 原始图片
└── redacted/                         # 脱敏输出
    ├── Luna Wang 25_redacted.pdf
    ├── W2_photo_redacted.pdf         # 图片 → PDF
    ├── 1099-DIV_redacted.pdf         # 图片 → PDF
    ├── redaction_map.txt
    └── redaction_map.csv
```

---

## 三、脱敏规则

### 3.1 处理方式分类

脱敏处理分为三种方式：

| 方式 | 说明 | 适用场景 |
|---|---|---|
| **删除（X 替换）** | 用同格式的 X 字符替换原始内容 | 不相关的 PII，如 SSN、银行账号 |
| **Token 化** | 用有意义的代号替换 | 需要跨表关联的信息，如姓名、雇主名 |
| **保留** | 不做任何处理 | 审查必需的信息，如金额、Filing Status |

### 3.2 逐项脱敏规则

| # | 项目 | 处理方式 | 脱敏后显示 | 理由 |
|---|---|---|---|---|
| 1 | SSN（纳税人） | X 替换 | `XXX-XX-XXXX` | 不相关，保留格式让用户知道原来填过 |
| 2 | SSN（配偶） | X 替换 | `XXX-XX-XXXX` | 同上 |
| 3 | SSN（Dependent） | X 替换 | `XXX-XX-XXXX` | 同上 |
| 4 | SSN（父母，Form 8615） | X 替换 | `XXX-XX-XXXX` | 同上 |
| 5 | 银行账号 | X 替换 | `XXXXXXXXXXXXX` | 不相关 |
| 6 | Routing Number | X 替换 | `XXXXXXXXX` | 不相关 |
| 7 | 电话号码 | X 替换 | `(XXX) XXX-XXXX` | 不相关 |
| 8 | EIN（雇主税号） | Token 化 | `Employer-1` | 需要区分多个雇主 |
| 9 | Broker 账号 | Token 化 | `Broker-1` | 需要区分多个 broker |
| 10 | Preparer 信息 | X 替换 | `XXXXXX` | 不相关，不需要区分 |
| 11 | 完整地址（纳税人） | 部分保留 | `XXXX XXXXX, CA XXXXX` | 只保留 State（有税务用途） |
| 12 | 完整地址（雇主） | X 替换 | `XXXX XXXXX XXXXX` | 不相关 |
| 13 | 出生日期 | 部分保留 | `05/XX/2008` | 保留月/年（精确计算税年末年龄需要） |
| 14 | 纳税人姓名 | Token 化 | `Taxpayer-A` | 需要跨表关联 |
| 15 | 配偶姓名 | Token 化 | `Spouse-A` | 需要跨表关联 |
| 16 | 雇主名称 | Token 化 | `Employer-1` | 与 EIN 用同一个 Token |
| 17 | Dependent 姓名 | Token 化 | `Dependent-1`, `Dependent-2` | 需要关联 |
| 18 | 父母姓名（Form 8615） | Token 化 | `Parent-1` | 需要关联 |
| 19 | 所有金额数字 | **保留** | 不变 | 审查核心数据 |
| 20 | Filing Status | **保留** | 不变 | 审查必需，不敏感 |
| 21 | 职业（Occupation） | **保留** | 不变 | 审查有用，不敏感 |

### 3.3 Token 分配逻辑

**同一个真实值 → 同一个 Token。** 程序维护一个内存中的映射表：

1. 遇到一个姓名时，检查映射表中是否已存在
2. 如果已存在，使用已分配的 Token
3. 如果不存在，分配新 Token

示例：W-2 雇主名 "Wenguang Wang" 和 Form 8615 父母名 "Wenguang Wang" 是同一个字符串 → 分配同一个 Token（如 `Employer-1`，同时也是 `Parent-1` 的候选）。

**跨角色的同名处理：** 如果一个人同时是雇主和父母，程序检测到同名后，两个角色使用同一个 Token。Token 命名取第一次出现时的角色（如先在 W-2 中出现则为 `Employer-1`）。

### 3.4 PII 检测方法

MVP 阶段使用正则表达式和位置规则进行 PII 检测：

| PII 类型 | 检测方法 |
|---|---|
| SSN | 正则：`\d{3}-\d{2}-\d{4}` |
| EIN | 正则：`\d{2}-\d{7}` |
| 电话 | 正则：`\(\d{3}\)\s*\d{3}-\d{4}` 及其变体 |
| 银行账号/Routing | 1040 Direct Deposit 区域的数字字段 |
| 姓名 | 税表固定位置（如 1040 首页 Name 区域、W-2 Box c/e） |
| 地址 | 税表固定位置（如 1040 Home address 区域） |
| 出生日期 | 税表固定位置 + 日期格式正则 |

**对于 PDF 文件：** 利用 PDF 的文本层定位字段。TurboTax/H&R Block 生成的 PDF 通常有良好的文本层。

**对于图片文件：** 先 OCR 识别文字和位置，再应用同样的检测规则。

---

## 四、映射表格式

### redaction_map.txt（给用户看）

```
TaxShield 脱敏映射表
请妥善保管，勿发送给第三方
生成时间：2026-03-30
源文件目录：/Users/xxx/tax_documents/

代号              → 原始信息
──────────────────────────────────────
Taxpayer-A        → Luna H Wang
Parent-1          → Wenguang Wang
Employer-1        → Wenguang Wang
Broker-1          → Morgan Stanley (Acct: 120315365)

备注：
- Employer-1 与 Parent-1 为同一人
```

### redaction_map.csv（给 TaxReveal 反脱敏程序用）

```csv
token,original,note
Taxpayer-A,Luna H Wang,
Parent-1,Wenguang Wang,same_as:Employer-1
Employer-1,Wenguang Wang,same_as:Parent-1
Broker-1,"Morgan Stanley (Acct: 120315365)",
```

---

## 五、技术设计

### 5.1 技术栈

| 组件 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.10+ | 生态丰富，PDF/OCR 库成熟 |
| PDF 读取 | PyMuPDF (fitz) | 读取 PDF 文本层和位置信息 |
| PDF 修改 | PyMuPDF (fitz) | 原地修改 PDF 文本/覆盖区域 |
| OCR | Tesseract (pytesseract) | 开源 OCR，处理图片输入 |
| 图片处理 | Pillow | 图片读取、遮盖区域绘制 |
| 图片转 PDF | img2pdf 或 PyMuPDF | 将处理后的图片嵌入 PDF |
| CLI | argparse 或 click | 命令行参数解析 |

### 5.2 处理流程

```
输入（文件或目录）
    ↓
遍历所有文件
    ↓
对每个文件：
    ↓
判断格式（PDF / 图片）
    ↓
┌─────────────────┬──────────────────┐
│ PDF             │ 图片（JPG/PNG）   │
│                 │                  │
│ 提取文本层 +    │ OCR 识别文字 +   │
│ 位置信息        │ 位置信息          │
└────────┬────────┴────────┬─────────┘
         ↓                 ↓
    统一的文字 + 位置数据结构
         ↓
    PII 检测（正则 + 位置规则）
         ↓
    Token 分配（查映射表，同名同 Token）
         ↓
┌─────────────────┬──────────────────┐
│ PDF             │ 图片             │
│                 │                  │
│ 用白色矩形覆盖  │ 在图片上画白色   │
│ 原文字区域，    │ 矩形覆盖原文字， │
│ 写入替换文字    │ 写入替换文字，   │
│                 │ 转换为 PDF       │
└────────┬────────┴────────┬─────────┘
         ↓                 ↓
    保存到 redacted/ 子目录
         ↓
    生成映射表（.txt + .csv）
```

### 5.3 项目结构

```
TaxShield/
├── README.md                    # 项目说明
├── design.md                    # 本设计文档
├── LICENSE                      # MIT License
├── setup.py                     # 安装配置
├── requirements.txt             # 依赖
├── taxshield/                   # 主程序包
│   ├── __init__.py
│   ├── cli.py                   # 命令行入口
│   ├── redactor.py              # 脱敏主逻辑（调度）
│   ├── pdf_processor.py         # PDF 读取/修改
│   ├── image_processor.py       # 图片 OCR/修改/转 PDF
│   ├── pii_detector.py          # PII 检测（正则 + 位置规则）
│   ├── tokenizer.py             # Token 分配和映射表管理
│   ├── map_writer.py            # 映射表输出（.txt + .csv）
│   └── tax_form_fields.py       # 税表字段位置定义（各表格的 PII 区域）
└── tests/
    ├── test_pii_detector.py
    ├── test_tokenizer.py
    └── test_redactor.py
```

### 5.4 命令行接口

只有一个命令 `redact`：

```bash
# 单个文件
taxshield redact "Luna Wang 25.pdf"

# 多个文件
taxshield redact "Luna Wang 25.pdf" "W2_photo.jpg" "1099-DIV.png"

# 目录（自动处理所有 PDF 和图片，忽略其他文件）
taxshield redact ./tax_documents/

# 预览模式（只显示检测到的 PII，不执行脱敏）
taxshield redact ./tax_documents/ --preview

# 指定输出目录
taxshield redact ./tax_documents/ --output ./output/

# 版本信息
taxshield --version
```

**`--preview` 参数：** 只检测和显示 PII，不修改任何文件。用户可以在脱敏前确认检测结果是否正确。

**输出目录逻辑：**
- 输入是目录：输出到该目录下的 `redacted/` 子目录
- 输入是文件（一个或多个）：输出到这些文件的父目录下的 `redacted/` 子目录
- 输入文件分散在不同目录：报错，要求使用 `--output` 指定输出目录

**文件类型自动判断：** 程序通过文件头（magic bytes）自动识别文件类型，不依赖后缀名。PDF 文件头为 `%PDF`，JPEG 为 `FF D8 FF`，PNG 为 `89 50 4E 47`。后缀名作为 fallback。目录模式下自动处理所有识别为 PDF 或图片的文件，忽略其他文件。

---

## 六、参考规范

本工具的设计参考了以下行业规范和最佳实践：

| 规范 | 适用性 | 说明 |
|---|---|---|
| **NIST SP 800-122** | PII 定义 | 定义了 PII 的范围：姓名、SSN、出生日期等 |
| **NIST SP 800-188** | 去标识化方法 | 政府数据去标识化指南，pseudonymization 方法参考 |
| **NISTIR 8053** | 术语和概念 | 去标识化和重标识化的术语定义 |
| **IRS Publication 1075** | FTI 定义 | 定义了联邦税务信息（FTI）的范围：SSN、姓名、地址、收入等均属 FTI |
| **IRS Publication 4557** | 税务从业者安全要求 | 税务专业人员的数据保护要求参考 |

**注意：** IRS Pub 1075 规定 FTI 不能通过遮盖来规避 IRC § 6103 的保密要求。这一条适用于政府机构处理 FTI 的场景。本工具的场景不同——是用户对**自己的**税表进行脱敏后自愿提交给第三方审查服务，用户有权处置自己的信息。

---

## 七、已知局限性

| 局限性 | 影响 | 缓解措施 |
|---|---|---|
| 正则匹配可能漏检 | 某些非标准格式的 PII 可能未被检测到 | `scan` 命令让用户预览；后续版本加入 NER |
| 图片 OCR 可能不准 | 模糊/倾斜的图片可能识别错误 | 在输出中标注 OCR 置信度低的区域 |
| 手写文字处理困难 | 手写的 W-2 等 OCR 准确率低 | 标注为"建议用户手动检查" |
| 只支持美国联邦税表 | 不支持州税表和其他国家税表 | 明确说明适用范围 |
| PDF 文本层缺失 | 扫描件 PDF 无文本层，需要 OCR | 自动检测并切换到 OCR 模式 |

---

## 八、开发计划

### MVP（第一版）
- [ ] PDF 文本层处理（TurboTax/H&R Block 输出的 PDF）
- [ ] 正则 PII 检测（SSN、EIN、电话、银行账号）
- [ ] 固定位置 PII 检测（姓名、地址——基于税表已知布局）
- [ ] Token 化姓名/雇主名
- [ ] X 替换不相关 PII
- [ ] 映射表生成（.txt + .csv）
- [ ] `redact` 和 `scan` 命令
- [ ] 单元测试

### 后续版本
- [ ] 图片输入支持（OCR + 图片脱敏 + 转 PDF）
- [ ] NER 辅助 PII 检测
- [ ] 更多税表类型支持
- [ ] GUI 界面（可选）
