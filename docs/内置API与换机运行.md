# 内置 API 与换一台机器怎么跑

这份说明回答两个问题：模型从哪里来、换台电脑或放到手机后端上还要改什么。
结论先说：**不用改代码，只改 `mednexus/.env` 里的几行**。

## 一、三层降级（这是写在申报表里的"安全合规"得分点）

| 顺序 | 用什么 | 什么时候用 | 数据去哪 |
| --- | --- | --- | --- |
| 1 | 内置云端 API（当前智谱 `glm-4-flash`） | 有 `.env` 且填了密钥，默认走这里 | 发往配置的模型服务 |
| 2 | 本机 Ollama（`qwen3:4b`） | 没配密钥、或 `MEDNEXUS_CLOUD=0` | 不出本机 |
| 3 | 纯摘录式（不调模型） | 两者都不可用或调用失败 | 不出本机 |

三层都是自动切换，界面右上和卡片上会如实显示当前用的是哪一层，不会假装有模型。
第 3 层不是"降级残废"：页码引用、逐条回查、拒答这些判定本来就全在检索层和校验层，
没有模型也能给出"《生理学（第10版）》P284 原文摘录"。

## 二、`.env` 字段

复制 `.env.example` 为 `.env` 再填。`.env` 已被 `.gitignore` 忽略，不会推到仓库。

| 字段 | 作用 | 默认 |
| --- | --- | --- |
| `MEDNEXUS_BASE_URL` | OpenAI 兼容接口前缀，要带版本段 | `https://api.deepseek.com/v1` |
| `MEDNEXUS_MODEL` | 模型名 | `deepseek-chat` |
| `MEDNEXUS_API_KEY` | 密钥，留空等于不联网 | 空 |
| `MEDNEXUS_CLOUD` | 设 `0` 强制只用本机 Ollama | `1` |
| `MEDNEXUS_ASK_MODEL` | 教材答疑是否交给模型组织语言 | `0`（关闭） |
| `MEDNEXUS_TUTOR_URL` | 本机 Ollama 地址，只接受 127.0.0.1/localhost | `http://127.0.0.1:11434` |
| `MEDNEXUS_TUTOR_MODEL` | 指定 Ollama 模型名，空则自动挑 qwen3 | 空 |
| `MEDNEXUS_NCBI_EMAIL` | PubMed 检索邮箱，可提高配额 | 空 |

`server.py` 启动时会自动读 `mednexus/.env` 与仓库根目录的 `.env`，
已经存在的同名环境变量优先（方便临时覆盖）。改完 `.env` 要**重启服务**才生效。

## 三、可用的免费/低价接口

只需 OpenAI 兼容 + 支持 `response_format: json_object`（不支持会自动退回普通模式，慢一点）。

| 提供方 | 接口前缀 | 模型 | 备注 |
| --- | --- | --- | --- |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | 免费档，实测 1.8–3.3 s，本仓库当前用它 |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` | 新用户有免费额度 |
| 深度求索 | `https://api.deepseek.com/v1` | `deepseek-chat` | 便宜、中文稳，需充值 |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` | 有免费模型 |
| 学校大模型农场 | 问管理员要 | 问管理员要 | 数据不出校，最适合写进申报表 |

问学校农场时确认四件事：给的是 API 还是网页账号、是否 OpenAI 兼容
（`/v1/chat/completions`）、数据是否出校、有无并发限流。

学校农场 = "云端但不出校"，在"数据安全"这条上比商业 API 更好讲。

## 四、换到另一台电脑 / 手机后端

1. 把仓库拷过去（或 `git clone`），`chunks.jsonl` 单独带上（4.2 MB，在 `.gitignore` 里，
   不随仓库走；没有它就没有教材页码，只能用自编学习卡）。
2. 新建 `.env`，填 `MEDNEXUS_BASE_URL` / `MEDNEXUS_MODEL` / `MEDNEXUS_API_KEY`。
3. `python server.py`。**不需要装 Ollama**，也不需要显卡。
4. 手机上只是浏览器访问同一个地址，前端不用打包；真要放到云服务器，
   把 `server.py` 跑在服务器上、手机用浏览器打开即可（注意加访问控制，
   当前只做了本机与内网放行）。

## 五、隐私口径（申报表别写错）

- 第 1 层：学生提问与自编学习卡会发往所配置的模型服务，界面已如实标注服务名。
  教材原文摘录只发命中的那一段（上限 600 字），不发整本书。
- 第 2 层：对话只在本机 Ollama，代码里把地址强制限定为 127.0.0.1/localhost/::1，
  配错了会直接抛错而不是偷偷发出去。
- 第 3 层：不产生任何网络请求。
- 无论哪一层：不收集真实患者信息，不接校内业务库，全部用公开教材与模拟学习记录。

## 六、改完怎么验

```powershell
# 服务起来后看一眼当前用的是哪一层
curl http://127.0.0.1:7860/api/overview
# status 里应有 {"llm": true, "model": "glm-4-flash", ...}

# 教学对话当前 provider（需要先取一个练习题 token）
curl "http://127.0.0.1:7860/api/tutor?token=<任务token>"
# provider.mode 为 cloud / ollama / local_materials 之一，label 会显示具体模型名
```